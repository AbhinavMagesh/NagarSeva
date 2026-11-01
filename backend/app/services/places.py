import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_retryable(error: BaseException) -> bool:
    return isinstance(error, httpx.TransportError) or (
        isinstance(error, httpx.HTTPStatusError)
        and (error.response.status_code == 429 or error.response.status_code >= 500)
    )


retry_provider = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)


@retry_provider
async def geocode(address: str) -> dict | None:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "jsonv2", "addressdetails": 1, "limit": 1, "countrycodes": "in"},
            headers={"User-Agent": "NagarSeva/1.0 (civic grievance reporting)"},
        )
        response.raise_for_status()
    matches = response.json()
    if not matches:
        return None
    match = matches[0]
    parts = match.get("address", {})
    return {
        "lat": float(match["lat"]),
        "lng": float(match["lon"]),
        "address": match.get("display_name", address),
        "district": parts.get("state_district") or parts.get("county") or parts.get("city"),
        "state": parts.get("state"),
    }


@retry_provider
async def reverse_geocode(lat: float, lng: float) -> dict | None:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lng, "format": "jsonv2", "addressdetails": 1},
            headers={"User-Agent": "NagarSeva/1.0 (civic grievance reporting)"},
        )
        response.raise_for_status()
    result = response.json()
    parts = result.get("address", {})
    return {
        "address": result.get("display_name"),
        "district": parts.get("state_district") or parts.get("county") or parts.get("city"),
        "state": parts.get("state"),
    }


@retry_provider
async def nearby_critical_places(lat: float, lng: float) -> list[tuple[str, float]]:
    query = f"""[out:json][timeout:20];
    (node(around:500,{lat},{lng})[amenity~"hospital|school|clinic"];
     way(around:500,{lat},{lng})[amenity~"hospital|school|clinic"];
     node(around:500,{lat},{lng})[bridge];
     way(around:500,{lat},{lng})[bridge];
     node(around:500,{lat},{lng})[highway~"motorway|trunk|primary"];
     way(around:500,{lat},{lng})[highway~"motorway|trunk|primary"];);
    out center tags;"""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": "NagarSeva/1.0 (civic grievance triage)"},
        )
        response.raise_for_status()
    from math import asin, cos, radians, sin, sqrt

    results = []
    for element in response.json().get("elements", []):
        tags = element.get("tags", {})
        target_lat = element.get("lat", element.get("center", {}).get("lat"))
        target_lng = element.get("lon", element.get("center", {}).get("lon"))
        if target_lat is None or target_lng is None:
            continue
        dlat, dlng = radians(float(target_lat) - lat), radians(float(target_lng) - lng)
        haversine = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(float(target_lat))) * sin(dlng / 2) ** 2
        distance = 6_371_000 * 2 * asin(sqrt(haversine))
        if tags.get("bridge"):
            kind = "bridge"
        elif tags.get("highway") in {"motorway", "trunk", "primary"}:
            kind = "highway"
        else:
            kind = tags.get("amenity", "critical")
        results.append((kind, distance))
    return results


@retry_provider
async def current_weather(lat: float, lng: float) -> dict:
    from app.config import settings

    if not settings.openweathermap_api_key:
        raise RuntimeError("OPENWEATHERMAP_API_KEY is missing; configure it in backend/.env.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lng, "appid": settings.openweathermap_api_key, "units": "metric"},
        )
        response.raise_for_status()
    data = response.json()
    try:
        return {
            "rain_mm": data.get("rain", {}).get("1h", 0),
            "weather": data["weather"][0]["main"],
            "description": data["weather"][0]["description"],
            "temperature_c": data["main"]["temp"],
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("OpenWeatherMap returned an incomplete weather response.") from exc
