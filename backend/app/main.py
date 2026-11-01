import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from geoalchemy2 import Geography, WKTElement
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import bearer, create_access_token, get_current_user, hash_password, require_authority, verify_password
from app.config import settings
from app.database import SessionLocal, get_db, initialize_database
from app.models import Department, Grievance, TimelineEntry, User, VerificationResponse
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, StatusUpdate, VerificationRequest
from app.services import realtime
from app.services.pipeline import process_report, serialize_grievance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nagarseva")
scheduler = AsyncIOScheduler(timezone="UTC")


async def check_escalations() -> None:
    with SessionLocal() as db:
        overdue = db.query(Grievance).filter(
            Grievance.sla_deadline < datetime.now(timezone.utc),
            Grievance.status.notin_(["RESOLVED", "VERIFIED_RESOLVED", "CLOSED", "REJECTED", "FAILED"]),
            Grievance.escalation_level < 2,
        ).all()
        for grievance in overdue:
            grievance.escalation_level += 1
            grievance.status = "ESCALATED"
            grievance.updated_at = datetime.now(timezone.utc)
            db.add(TimelineEntry(
                grievance_id=grievance.id,
                action="ESCALATED",
                performed_by="ESCALATION_AGENT",
                details={"escalation_level": grievance.escalation_level},
            ))
            db.commit()
            await realtime.publish("grievance_escalated", serialize_grievance(db, grievance))


async def request_verification() -> None:
    with SessionLocal() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        candidates = db.query(Grievance).filter(
            (Grievance.status == "IN_PROGRESS")
            | ((Grievance.status == "ASSIGNED") & (Grievance.created_at < cutoff))
        ).all()
        for grievance in candidates:
            recent = db.query(VerificationResponse).filter(
                VerificationResponse.grievance_id == grievance.id,
                VerificationResponse.responded_at > datetime.now(timezone.utc) - timedelta(days=3),
            ).first()
            if recent:
                continue
            db.add(TimelineEntry(
                grievance_id=grievance.id,
                action="VERIFICATION_SENT",
                performed_by="VERIFICATION_AGENT",
                details={"method": "live dashboard"},
            ))
            db.commit()
            await realtime.publish("verification_requested", serialize_grievance(db, grievance))


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(settings.jwt_secret) < 32 or settings.jwt_secret == "change-me-before-deployment":
        raise RuntimeError("Set JWT_SECRET to at least 32 random characters in backend/.env.")
    initialize_database()
    scheduler.add_job(check_escalations, "interval", hours=6, id="sla-escalations", replace_existing=True)
    scheduler.add_job(request_verification, "interval", days=1, id="verification-requests", replace_existing=True)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


api = FastAPI(title="NagarSeva API", version="1.0.0", lifespan=lifespan)
api.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _upload_error(file: UploadFile, data: bytes, allowed: set[str], max_bytes: int) -> None:
    if file.content_type not in allowed:
        raise HTTPException(415, f"Unsupported file type: {file.content_type}.")
    if not data:
        raise HTTPException(400, "Uploaded file is empty.")
    if len(data) > max_bytes:
        raise HTTPException(413, "Uploaded file exceeds the allowed size.")


def _new_tracking_id(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    while True:
        tracking_id = f"NGS-{year}-{secrets.randbelow(99999) + 1:05d}"
        if not db.query(Grievance).filter_by(tracking_id=tracking_id).first():
            return tracking_id


def get_optional_user(
    credentials=Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    return get_current_user(credentials, db)


async def _create_report(
    db: Session,
    background_tasks: BackgroundTasks,
    *,
    source: str,
    images: list[tuple[str, str, bytes]],
    audio: tuple[str, str, bytes] | None,
    description: str,
    latitude: float | None,
    longitude: float | None,
    language: str,
    reporter: User | None,
) -> dict:
    if (latitude is None) != (longitude is None):
        raise HTTPException(422, "Latitude and longitude must be provided together.")
    if latitude is not None and (not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise HTTPException(422, "Coordinates are outside the valid range.")
    if not images and not audio and not description.strip():
        raise HTTPException(422, "Add a photo or voice recording, or enter a description.")
    if images and len(images) > 5:
        raise HTTPException(422, "A maximum of five images can be uploaded.")

    grievance = Grievance(
        tracking_id=_new_tracking_id(db),
        title="Report is being processed",
        description=description.strip() or "Report is being processed.",
        source=source,
        reporter_id=reporter.id if reporter else None,
        status="PROCESSING",
        location=WKTElement(f"POINT({longitude} {latitude})", srid=4326) if latitude is not None else None,
        severity_score=0,
        severity_label="PENDING",
    )
    db.add(grievance)
    db.commit()
    db.refresh(grievance)
    db.add(TimelineEntry(
        grievance_id=grievance.id,
        action="CREATED",
        performed_by=str(reporter.id) if reporter else "SYSTEM",
        details={"source": source},
    ))
    db.commit()
    await realtime.publish("new_grievance", serialize_grievance(db, grievance))
    background_tasks.add_task(
        process_report,
        grievance.id,
        images,
        audio,
        description.strip(),
        latitude,
        longitude,
        language,
    )
    return {
        "tracking_id": grievance.tracking_id,
        "grievance_id": str(grievance.id),
        "status": grievance.status,
        "message": "Report received. Follow its analysis live on the dashboard.",
    }


@api.get("/health")
def health() -> dict:
    return {"status": "ok"}


@api.post("/api/v1/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = payload.email.lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(409, "An account with this email already exists.")
    department = None
    if payload.role == "authority":
        if not settings.admin_invite_code or payload.invite_code != settings.admin_invite_code:
            raise HTTPException(403, "A valid authority invitation code is required.")
        if not payload.department_code:
            raise HTTPException(422, "Authority registration requires a department code.")
        department = db.query(Department).filter_by(code=payload.department_code.upper()).first()
        if not department:
            raise HTTPException(422, "Unknown department code.")
    user = User(
        email=email,
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        department_id=department.id if department else None,
        jurisdiction_area=payload.jurisdiction_area,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return AuthResponse(access_token=create_access_token(user), user=user)


@api.post("/api/v1/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    return AuthResponse(access_token=create_access_token(user), user=user)


@api.post("/api/v1/grievances/file-image", status_code=201)
async def file_image(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    description: str = Form(""),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    db: Session = Depends(get_db),
    reporter: User | None = Depends(get_optional_user),
) -> dict:
    if len(images) > 5:
        raise HTTPException(422, "A maximum of five images can be uploaded.")
    image_data = []
    for image in images:
        content = await image.read(10 * 1024 * 1024 + 1)
        _upload_error(image, content, {"image/jpeg", "image/png", "image/webp"}, 10 * 1024 * 1024)
        image_data.append((Path(image.filename or "report.jpg").name, image.content_type or "", content))
    return await _create_report(
        db, background_tasks, source="WEB_IMAGE", images=image_data, audio=None,
        description=description, latitude=latitude, longitude=longitude, language="",
        reporter=reporter,
    )


@api.post("/api/v1/grievances/file-voice", status_code=201)
async def file_voice(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    description: str = Form(""),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    language_hint: str = Form("unknown"),
    db: Session = Depends(get_db),
    reporter: User | None = Depends(get_optional_user),
) -> dict:
    content = await audio.read(25 * 1024 * 1024 + 1)
    _upload_error(
        audio, content,
        {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/flac"},
        25 * 1024 * 1024,
    )
    audio_data = (Path(audio.filename or "report.wav").name, audio.content_type or "", content)
    return await _create_report(
        db, background_tasks, source="VOICE_RECORDING", images=[], audio=audio_data,
        description=description, latitude=latitude, longitude=longitude, language=language_hint,
        reporter=reporter,
    )


@api.get("/api/v1/grievances")
def list_grievances(
    status_filter: str | None = Query(None, alias="status"),
    category: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = db.query(Grievance)
    if status_filter:
        query = query.filter(Grievance.status == status_filter.upper())
    if category:
        query = query.filter(Grievance.category == category.upper())
    return [serialize_grievance(db, item) for item in query.order_by(Grievance.created_at.desc()).offset(offset).limit(limit)]


@api.get("/api/v1/grievances/{grievance_id}")
def grievance_detail(grievance_id: UUID, db: Session = Depends(get_db)) -> dict:
    grievance = db.get(Grievance, grievance_id)
    if not grievance:
        raise HTTPException(404, "Grievance not found.")
    return serialize_grievance(db, grievance)


@api.get("/api/v1/grievances/{grievance_id}/timeline")
def grievance_timeline(grievance_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    if not db.get(Grievance, grievance_id):
        raise HTTPException(404, "Grievance not found.")
    entries = db.query(TimelineEntry).filter_by(grievance_id=grievance_id).order_by(TimelineEntry.created_at).all()
    return [{
        "action": entry.action,
        "details": entry.details,
        "created_at": entry.created_at.isoformat(),
    } for entry in entries]


@api.patch("/api/v1/grievances/{grievance_id}/status")
async def update_status(
    grievance_id: UUID,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    authority: User = Depends(require_authority),
) -> dict:
    grievance = db.get(Grievance, grievance_id)
    if not grievance:
        raise HTTPException(404, "Grievance not found.")
    if authority.role != "admin" and grievance.assigned_department_id != authority.department_id:
        raise HTTPException(403, "This grievance is assigned to another department.")
    old_status = grievance.status
    grievance.status = payload.status
    grievance.updated_at = datetime.now(timezone.utc)
    if payload.status == "RESOLVED":
        grievance.resolved_at = datetime.now(timezone.utc)
    db.add(TimelineEntry(
        grievance_id=grievance.id,
        action="STATUS_CHANGED",
        old_value=old_status,
        new_value=payload.status,
        performed_by=str(authority.id),
        details={"comment": payload.comment} if payload.comment else {},
    ))
    db.commit()
    data = serialize_grievance(db, grievance)
    await realtime.publish("grievance_updated", data)
    return data


@api.get("/api/v1/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)) -> dict:
    counts = dict(db.query(Grievance.status, func.count()).group_by(Grievance.status).all())
    total = sum(counts.values())
    return {
        "total": total,
        "resolved": counts.get("RESOLVED", 0) + counts.get("VERIFIED_RESOLVED", 0),
        "pending": sum(count for key, count in counts.items() if key not in {"RESOLVED", "VERIFIED_RESOLVED", "CLOSED", "REJECTED", "FAILED"}),
        "sla_breached": db.query(func.count()).select_from(Grievance).filter(
            Grievance.sla_deadline < datetime.now(timezone.utc),
            Grievance.status.notin_(["RESOLVED", "VERIFIED_RESOLVED", "CLOSED", "REJECTED", "FAILED"]),
        ).scalar(),
        "by_status": counts,
    }


@api.get("/api/v1/dashboard/heatmap")
def dashboard_heatmap(
    severity_min: float = Query(0, ge=0, le=10),
    db: Session = Depends(get_db),
) -> dict:
    grievances = db.query(Grievance).filter(
        Grievance.location.is_not(None),
        Grievance.severity_score >= severity_min,
    ).order_by(Grievance.created_at.desc()).limit(1000).all()
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [item["lng"], item["lat"]]},
            "properties": item,
        } for item in (serialize_grievance(db, grievance) for grievance in grievances)],
    }


@api.get("/api/v1/dashboard/severity-distribution")
def severity_distribution(db: Session = Depends(get_db)) -> dict:
    return dict(db.query(Grievance.severity_label, func.count()).group_by(Grievance.severity_label).all())


@api.get("/api/v1/dashboard/category-breakdown")
def category_breakdown(db: Session = Depends(get_db)) -> dict:
    return dict(db.query(Grievance.category, func.count()).group_by(Grievance.category).all())


@api.get("/api/v1/dashboard/authority-scorecard")
def authority_scorecard(db: Session = Depends(get_db)) -> list[dict]:
    departments = db.query(Department).order_by(Department.name).all()
    results = []
    for department in departments:
        assigned = db.query(Grievance).filter_by(assigned_department_id=department.id).all()
        resolved = sum(item.status in {"RESOLVED", "VERIFIED_RESOLVED"} for item in assigned)
        results.append({
            "department": department.name,
            "total_assigned": len(assigned),
            "total_resolved": resolved,
            "resolution_rate_pct": round(resolved / len(assigned) * 100, 1) if assigned else 0,
        })
    return results


@api.get("/api/v1/dashboard/live-feed")
def live_feed(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)) -> list[dict]:
    grievances = db.query(Grievance).order_by(Grievance.created_at.desc()).limit(limit).all()
    return [serialize_grievance(db, item) for item in grievances]


@api.get("/api/v1/dashboard/trends")
def dashboard_trends(
    period: Literal["week", "month"] = Query("week"),
    db: Session = Depends(get_db),
) -> list[dict]:
    buckets = db.query(
        func.date_trunc(period, Grievance.created_at).label("bucket"),
        func.count().label("count"),
    ).group_by("bucket").order_by("bucket").all()
    return [{"period": bucket.isoformat(), "count": count} for bucket, count in buckets]


@api.get("/api/v1/verify/nearby")
def nearby_for_verification(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    db: Session = Depends(get_db),
) -> list[dict]:
    results = db.query(Grievance).filter(
        Grievance.location.is_not(None),
        Grievance.status.in_(["ASSIGNED", "IN_PROGRESS", "ESCALATED"]),
        func.ST_DWithin(
            func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326).cast(Geography(srid=4326)),
            Grievance.location.cast(Geography(srid=4326)),
            500,
        ),
    ).order_by(Grievance.severity_score.desc()).limit(30).all()
    return [serialize_grievance(db, item) for item in results]


@api.put("/api/v1/users/location")
def update_user_location(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    user.location = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
    db.commit()
    return {"updated": True}


@api.post("/api/v1/verify/{grievance_id}", status_code=201)
async def verify_grievance(
    grievance_id: UUID,
    payload: VerificationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    grievance = db.get(Grievance, grievance_id)
    if not grievance:
        raise HTTPException(404, "Grievance not found.")
    if db.query(VerificationResponse).filter_by(grievance_id=grievance_id, user_id=user.id).first():
        raise HTTPException(409, "You have already submitted a verification for this issue.")
    db.add(VerificationResponse(
        grievance_id=grievance_id,
        user_id=user.id,
        is_resolved=payload.is_resolved,
        comment=payload.comment,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You have already submitted a verification for this issue.")
    recent = db.query(VerificationResponse).filter(
        VerificationResponse.grievance_id == grievance_id,
        VerificationResponse.responded_at > datetime.now(timezone.utc) - timedelta(hours=24),
    ).all()
    ratio = sum(response.is_resolved for response in recent) / len(recent)
    result = "INCONCLUSIVE"
    if ratio >= 0.7:
        grievance.status = "VERIFIED_RESOLVED"
        grievance.resolved_at = datetime.now(timezone.utc)
        result = "VERIFIED_RESOLVED"
    elif ratio <= 0.3:
        grievance.severity_score = min(10, grievance.severity_score + 0.5)
        grievance.severity_label = (
            "CRITICAL" if grievance.severity_score >= 8.5
            else "HIGH" if grievance.severity_score >= 7
            else "MEDIUM" if grievance.severity_score >= 4
            else "LOW"
        )
        result = "STILL_UNRESOLVED"
    db.add(TimelineEntry(
        grievance_id=grievance_id,
        action="VERIFICATION_AGGREGATED",
        performed_by="VERIFICATION_AGENT",
        details={"responses": len(recent), "resolved_ratio": round(ratio, 3), "result": result},
    ))
    db.commit()
    data = serialize_grievance(db, grievance)
    await realtime.publish("grievance_updated", data)
    return {"result": result, "response_count": len(recent), "grievance": data}


@api.get("/api/v1/admin/assigned")
def assigned_grievances(
    db: Session = Depends(get_db),
    authority: User = Depends(require_authority),
) -> list[dict]:
    query = db.query(Grievance)
    if authority.role != "admin":
        query = query.filter(Grievance.assigned_department_id == authority.department_id)
    return [serialize_grievance(db, item) for item in query.order_by(Grievance.created_at.desc()).limit(200)]


@api.get("/api/v1/admin/escalations")
def escalations(db: Session = Depends(get_db), _: User = Depends(require_authority)) -> list[dict]:
    items = db.query(Grievance).filter(Grievance.status == "ESCALATED").order_by(
        Grievance.severity_score.desc()
    ).limit(200).all()
    return [serialize_grievance(db, item) for item in items]


@api.get("/api/v1/admin/performance")
def authority_performance(db: Session = Depends(get_db), _: User = Depends(require_authority)) -> list[dict]:
    return authority_scorecard(db)


import socketio

app = socketio.ASGIApp(realtime.socket_server, other_asgi_app=api)
