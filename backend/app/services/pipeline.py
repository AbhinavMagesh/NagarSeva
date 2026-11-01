import math
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from geoalchemy2 import Geography, WKTElement
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Department, Grievance, TimelineEntry
from app.services import media, places, realtime
from app.services.gemini import gemini
from app.services.sarvam import sarvam

logger = logging.getLogger("nagarseva.pipeline")


CATEGORY_TO_DEPARTMENT = {
    "ROAD_DAMAGE": "PWD",
    "BRIDGE_DAMAGE": "PWD",
    "WATER_LEAK": "WATER",
    "SEWAGE": "SANITATION",
    "ELECTRICITY": "ELECTRICITY",
    "POLLUTION": "ENV",
    "GARBAGE": "SANITATION",
    "STREETLIGHT": "ELECTRICITY",
    "OTHER": "MUNICIPAL",
}
CATEGORY_RISK = {
    "BRIDGE_DAMAGE": 9.0,
    "ELECTRICITY": 8.0,
    "SEWAGE": 7.0,
    "WATER_LEAK": 6.5,
    "POLLUTION": 6.0,
    "ROAD_DAMAGE": 5.5,
    "GARBAGE": 4.0,
    "STREETLIGHT": 3.5,
    "OTHER": 5.0,
}
SLA_HOURS = {"CRITICAL": 24, "HIGH": 72, "MEDIUM": 168, "LOW": 336}
VALID_CATEGORIES = set(CATEGORY_TO_DEPARTMENT)
SIGNAL_WEIGHTS = {
    "visual_damage": 0.25,
    "text_urgency": 0.15,
    "category_risk": 0.15,
    "geospatial_context": 0.15,
    "weather_amplification": 0.08,
    "report_frequency": 0.07,
    "recency_decay": 0.05,
}


def calculate_severity(signals: dict[str, float]) -> tuple[float, str]:
    weight_total = sum(SIGNAL_WEIGHTS.values())
    score = sum(signals[name] * weight for name, weight in SIGNAL_WEIGHTS.items()) / weight_total
    score = round(max(1.0, min(10.0, score)), 1)
    label = "CRITICAL" if score >= 8.5 else "HIGH" if score >= 7 else "MEDIUM" if score >= 4 else "LOW"
    return score, label


def _require_score(result: dict, key: str) -> float:
    value = result.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 10:
        raise RuntimeError(f"Gemini returned an invalid {key}; expected a number from 0 to 10.")
    return float(value)


def _validate_image_analysis(value: object) -> dict:
    if not isinstance(value, dict):
        raise RuntimeError("Gemini did not return structured image damage analysis.")
    allowed = {
        "damage_extent": {"minor", "moderate", "severe", "critical"},
        "area_affected": {"small", "medium", "large"},
        "structural_risk": {"none", "low", "medium", "high"},
        "safety_hazard": {"none", "low", "medium", "high", "immediate"},
    }
    for field, values in allowed.items():
        if value.get(field) not in values:
            raise RuntimeError(f"Gemini returned an invalid image analysis field: {field}.")
    return value


def _timeline(db: Session, grievance_id: UUID, action: str, details: dict | None = None) -> None:
    db.add(TimelineEntry(
        grievance_id=grievance_id,
        action=action,
        performed_by="SYSTEM",
        details=details or {},
    ))
    db.commit()


async def process_report(
    grievance_id: UUID,
    image_files: list[tuple[str, str, bytes]],
    audio_file: tuple[str, str, bytes] | None,
    raw_text: str,
    latitude: float | None,
    longitude: float | None,
    language: str,
) -> None:
    from app.database import SessionLocal

    async def emit_progress(stage: str) -> None:
        await realtime.publish("grievance_processing", {"grievance_id": str(grievance_id), "stage": stage})

    with SessionLocal() as db:
        grievance = db.get(Grievance, grievance_id)
        if grievance is None:
            raise RuntimeError(f"Processing record {grievance_id} no longer exists.")
        try:
            await emit_progress("Uploading media")
            image_urls = []
            for name, mime_type, content in image_files:
                image_urls.append(await media.upload(content, f"{grievance_id}/{name}", "image"))
            audio_url = None
            if audio_file:
                audio_name, _, audio_bytes = audio_file
                audio_url = await media.upload(audio_bytes, f"{grievance_id}/{audio_name}", "video")

            transcript = None
            original_language = None
            translated_text = raw_text
            if audio_file:
                await emit_progress("Transcribing voice with Sarvam")
                transcript_result = await sarvam.transcribe_and_translate(
                    audio_file[2], audio_file[0], audio_file[1], language
                )
                transcript = transcript_result["transcript"]
                original_language = transcript_result["language"]
                translated_text = transcript_result["translation"]
            if not image_files and not translated_text.strip():
                raise RuntimeError("A voice report or a description with at least one image is required.")
            if image_files and not translated_text.strip():
                translated_text = "Please identify the civic issue shown in the attached image."

            location = None
            address_text = None
            if latitude is not None and longitude is not None:
                location = {"lat": latitude, "lng": longitude}
            if translated_text.strip():
                await emit_progress("Extracting issue details")
                prompt = (
                    "You are a civic grievance intake processor for India. Use only evidence in the report "
                    "and attached photos. Return one JSON object with title (under 100 chars), detailed "
                    "description, category (one of ROAD_DAMAGE, WATER_LEAK, SEWAGE, ELECTRICITY, POLLUTION, "
                    "BRIDGE_DAMAGE, GARBAGE, STREETLIGHT, OTHER), sub_category, mentioned_location (string "
                    "or null), urgency_cues (string array), and image_analysis (object with damage_extent "
                    "minor/moderate/severe/critical, area_affected small/medium/large, structural_risk "
                    "none/low/medium/high, safety_hazard none/low/medium/high/immediate; or null if no image). "
                    "Never invent a location; use null when the user has not identified one. "
                    f"Citizen report (English): {translated_text}"
                )
                extracted = await gemini.generate_json(prompt, [
                    (content, mime_type) for _, mime_type, content in image_files
                ])
                category = str(extracted.get("category", "OTHER")).upper()
                if category not in VALID_CATEGORIES:
                    raise RuntimeError("Gemini returned an unsupported grievance category.")
                if location is None and extracted.get("mentioned_location"):
                    geocoded = await places.geocode(str(extracted["mentioned_location"]))
                    if geocoded:
                        location = geocoded
                        address_text = geocoded["address"]
                elif location is not None:
                    reverse = await places.reverse_geocode(location["lat"], location["lng"])
                    if reverse:
                        location.update(reverse)
                        address_text = reverse.get("address")
                if location is None:
                    raise RuntimeError("Location is required. Allow location access or add a recognizable landmark.")
                title_value = extracted.get("title")
                description_value = extracted.get("description")
                if not isinstance(title_value, str) or not isinstance(description_value, str):
                    raise RuntimeError("Gemini did not return a valid report title and description.")
                title = title_value.strip()[:500]
                description = description_value.strip()
                if not title or not description:
                    raise RuntimeError("Gemini did not return a title and description for this report.")
                image_analysis = _validate_image_analysis(extracted.get("image_analysis")) if image_files else None
                embedding = await gemini.embedding(description)
                grievance.title = title
                grievance.description = description
                grievance.category = category
                grievance.sub_category = extracted.get("sub_category")
                grievance.raw_transcript = transcript
                grievance.raw_language = original_language
                grievance.image_urls = image_urls
                grievance.audio_url = audio_url
                grievance.description_embedding = embedding
                grievance.location = WKTElement(f"POINT({location['lng']} {location['lat']})", srid=4326)
                grievance.address = address_text or location.get("address")
                grievance.district = location.get("district")
                grievance.state = location.get("state")
                db.commit()
                _timeline(db, grievance.id, "INTAKE_COMPLETED", {"category": category})

                await emit_progress("Checking nearby duplicate reports")
                candidates = db.query(Grievance).filter(
                    Grievance.id != grievance.id,
                    Grievance.category == category,
                    Grievance.status.notin_(["RESOLVED", "VERIFIED_RESOLVED", "CLOSED", "REJECTED", "FAILED"]),
                    Grievance.description_embedding.is_not(None),
                    func.ST_DWithin(
                        Grievance.location.cast(Geography(srid=4326)),
                        func.ST_SetSRID(func.ST_MakePoint(location["lng"], location["lat"]), 4326).cast(Geography(srid=4326)),
                        200,
                    ),
                ).limit(100).all()
                duplicate = None
                if candidates:
                    def similarity(candidate: Grievance) -> float:
                        candidate_embedding = candidate.description_embedding
                        dot = sum(left * right for left, right in zip(embedding, candidate_embedding, strict=True))
                        left_norm = math.sqrt(sum(value * value for value in embedding))
                        right_norm = math.sqrt(sum(value * value for value in candidate_embedding))
                        return dot / (left_norm * right_norm) if left_norm and right_norm else 0

                    best = max(candidates, key=similarity, default=None)
                    if best and similarity(best) >= 0.85:
                        duplicate = best
                if duplicate:
                    duplicate.report_count += 1
                    duplicate.severity_score = min(10, duplicate.severity_score + 0.3)
                    grievance.is_duplicate = True
                    grievance.parent_grievance_id = duplicate.id
                    grievance.title = f"Duplicate report of {duplicate.tracking_id}"
                    grievance.severity_score = duplicate.severity_score
                    grievance.severity_label = duplicate.severity_label
                    grievance.status = "CLOSED"
                    db.commit()
                    _timeline(db, duplicate.id, "DUPLICATE_MERGED", {
                        "new_report_id": str(grievance.id),
                        "report_count": duplicate.report_count,
                    })
                    await realtime.publish("grievance_updated", serialize_grievance(db, duplicate))
                    await realtime.publish("grievance_processed", serialize_grievance(db, duplicate))
                    return

                await emit_progress("Assessing severity with live weather and map data")
                weather = await places.current_weather(location["lat"], location["lng"])
                nearby = await places.nearby_critical_places(location["lat"], location["lng"])
                vision = image_analysis or {}
                damage = {"minor": 2, "moderate": 5, "severe": 7.5, "critical": 10}
                area = {"small": 2, "medium": 5, "large": 8}
                risk = {"none": 0, "low": 3, "medium": 6, "high": 9}
                hazard = {"none": 0, "low": 2, "medium": 5, "high": 8, "immediate": 10}
                visual_score = (
                    damage.get(vision.get("damage_extent"), 5) * 0.3
                    + area.get(vision.get("area_affected"), 5) * 0.2
                    + risk.get(vision.get("structural_risk"), 3) * 0.25
                    + hazard.get(vision.get("safety_hazard"), 2) * 0.25
                )
                if not image_files:
                    text_assessment = await gemini.generate_json(
                        "Rate the physical severity and text urgency of this civic issue from 0 to 10. "
                        "Return JSON with visual_score, urgency_score, and a concise explanation. "
                        f"Report: {description}"
                    )
                    visual_score = _require_score(text_assessment, "visual_score")
                    urgency_score = _require_score(text_assessment, "urgency_score")
                    explanation = str(text_assessment.get("explanation", ""))
                else:
                    text_assessment = await gemini.generate_json(
                        "Rate the urgency of this civic issue from 0 to 10 and briefly explain. "
                        f"Report: {description}"
                    )
                    urgency_score = _require_score(text_assessment, "urgency_score")
                    explanation = str(text_assessment.get("explanation", ""))
                geo_score = 3.0
                multipliers = {"hospital": 2.5, "clinic": 2.5, "school": 2.0, "bridge": 2.5, "highway": 2.0}
                for kind, distance in nearby:
                    geo_score += multipliers.get(kind, 1.0) * max(0, 1 - distance / 500)
                geo_score = min(10, geo_score)
                weather_score = min(10, 3 + float(weather["rain_mm"]) * 0.8) if weather["rain_mm"] else 3.0
                frequency_score = min(10, 3 + math.log2(max(1, duplicate.report_count if duplicate else 1)) * 1.5)
                signals = {
                    "visual_damage": round(max(0, min(10, visual_score)), 1),
                    "text_urgency": round(max(0, min(10, urgency_score)), 1),
                    "category_risk": CATEGORY_RISK[category],
                    "geospatial_context": round(geo_score, 1),
                    "weather_amplification": round(weather_score, 1),
                    "report_frequency": round(frequency_score, 1),
                    "recency_decay": max(0.0, round(10 - (datetime.now(timezone.utc) - grievance.created_at).total_seconds() / 86400, 1)),
                    "weather": weather,
                    "nearby_critical_places": len(nearby),
                }
                score, label = calculate_severity(signals)
                await emit_progress("Routing to the responsible department")
                dept_code = CATEGORY_TO_DEPARTMENT[category]
                department = db.query(Department).filter_by(code=dept_code).one()
                authority = db.execute(
                    text(
                        "SELECT id FROM users WHERE role='authority' AND department_id=:department "
                        "ORDER BY (SELECT count(*) FROM grievances g WHERE g.assigned_authority_id=users.id "
                        "AND g.status NOT IN ('RESOLVED','CLOSED')) LIMIT 1"
                    ),
                    {"department": str(department.id)},
                ).first()
                now = datetime.now(timezone.utc)
                grievance.severity_score = score
                grievance.severity_label = label
                grievance.severity_explanation = explanation or f"{label.title()} severity based on visual, urgency, location, weather, and category signals."
                grievance.severity_signals = signals
                grievance.assigned_department_id = department.id
                grievance.assigned_authority_id = UUID(str(authority.id)) if authority else None
                grievance.sla_deadline = now + timedelta(hours=SLA_HOURS[label])
                grievance.status = "ASSIGNED"
                grievance.processing_error = None
                grievance.updated_at = now
                db.commit()
                _timeline(db, grievance.id, "TRIAGED", {
                    "score": score,
                    "label": label,
                    "signals": signals,
                    "department": department.name,
                })
                await realtime.publish("grievance_processed", serialize_grievance(db, grievance))
        except Exception as exc:
            logger.exception("Report processing failed for %s", grievance.tracking_id)
            error_message = str(exc)
            for secret in (
                settings.gemini_api_key,
                settings.sarvam_api_key,
                settings.openweathermap_api_key,
                settings.cloudinary_api_secret,
            ):
                if secret:
                    error_message = error_message.replace(secret, "[redacted]")
            db.rollback()
            grievance = db.get(Grievance, grievance_id)
            if grievance:
                grievance.status = "FAILED"
                grievance.processing_error = error_message[:2000]
                db.commit()
                _timeline(db, grievance_id, "PROCESSING_FAILED", {"error": error_message[:1000]})
            await realtime.publish("grievance_failed", {
                "grievance_id": str(grievance_id),
                "error": error_message,
            })


def serialize_grievance(db: Session, grievance: Grievance) -> dict:
    location = db.execute(
        text("SELECT ST_Y(location) AS lat, ST_X(location) AS lng FROM grievances WHERE id=:id"),
        {"id": str(grievance.id)},
    ).first() if grievance.location else None
    return {
        "id": str(grievance.id),
        "tracking_id": grievance.tracking_id,
        "title": grievance.title,
        "description": grievance.description,
        "category": grievance.category,
        "sub_category": grievance.sub_category,
        "lat": location.lat if location else None,
        "lng": location.lng if location else None,
        "address": grievance.address,
        "severity_score": grievance.severity_score,
        "severity_label": grievance.severity_label,
        "severity_explanation": grievance.severity_explanation,
        "severity_signals": grievance.severity_signals,
        "status": grievance.status,
        "sla_deadline": grievance.sla_deadline.isoformat() if grievance.sla_deadline else None,
        "report_count": grievance.report_count,
        "is_duplicate": grievance.is_duplicate,
        "parent_grievance_id": str(grievance.parent_grievance_id) if grievance.parent_grievance_id else None,
        "department": grievance.department.name if grievance.department else None,
        "image_urls": grievance.image_urls,
        "processing_error": grievance.processing_error,
        "created_at": grievance.created_at.isoformat() if grievance.created_at else None,
    }
