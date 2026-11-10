import asyncio

import httpx

from app.services import pipeline
from app.services.pipeline import CATEGORY_TO_DEPARTMENT, SIGNAL_WEIGHTS, calculate_severity


def test_category_routing_covers_every_supported_category() -> None:
    assert CATEGORY_TO_DEPARTMENT["ROAD_DAMAGE"] == "PWD"
    assert CATEGORY_TO_DEPARTMENT["WATER_LEAK"] == "WATER"
    assert CATEGORY_TO_DEPARTMENT["OTHER"] == "MUNICIPAL"
    assert len(CATEGORY_TO_DEPARTMENT) == 9


def test_severity_uses_available_real_signals_and_returns_bounded_score() -> None:
    signals = {name: 10 for name in SIGNAL_WEIGHTS}
    score, label = calculate_severity(signals)
    assert score == 10
    assert label == "CRITICAL"

    signals = {name: 0 for name in SIGNAL_WEIGHTS}
    score, label = calculate_severity(signals)
    assert score == 1
    assert label == "LOW"


def test_severity_weighting_is_normalized_without_unavailable_census_data() -> None:
    assert round(sum(SIGNAL_WEIGHTS.values()), 2) == 0.9
    values = {name: 0 for name in SIGNAL_WEIGHTS}
    values["category_risk"] = 10
    score, _ = calculate_severity(values)
    assert score == 1.7


def test_severity_context_keeps_working_when_overpass_is_unavailable(monkeypatch) -> None:
    async def current_weather(_: float, __: float) -> dict:
        return {"rain_mm": 0, "weather": "Clear", "description": "clear sky", "temperature_c": 25}

    async def nearby_critical_places(_: float, __: float) -> list:
        request = httpx.Request("POST", "https://overpass-api.de/api/interpreter")
        response = httpx.Response(502, request=request)
        raise httpx.HTTPStatusError("Bad Gateway", request=request, response=response)

    monkeypatch.setattr(pipeline.places, "current_weather", current_weather)
    monkeypatch.setattr(pipeline.places, "nearby_critical_places", nearby_critical_places)

    weather, nearby, warnings = asyncio.run(
        pipeline._load_severity_context(47.0, 8.0, "NGS-test")
    )

    assert weather is not None
    assert nearby is None
    assert warnings == [
        "Nearby infrastructure data unavailable (HTTP 502); severity uses remaining signals."
    ]


def test_severity_context_keeps_working_when_weather_is_unavailable(monkeypatch) -> None:
    async def current_weather(_: float, __: float) -> dict:
        raise RuntimeError("Weather API key is missing.")

    async def nearby_critical_places(_: float, __: float) -> list:
        return [("school", 100.0)]

    monkeypatch.setattr(pipeline.places, "current_weather", current_weather)
    monkeypatch.setattr(pipeline.places, "nearby_critical_places", nearby_critical_places)

    weather, nearby, warnings = asyncio.run(
        pipeline._load_severity_context(47.0, 8.0, "NGS-test")
    )

    assert weather is None
    assert nearby == [("school", 100.0)]
    assert warnings == [
        "Weather data unavailable (RuntimeError); severity uses remaining signals."
    ]
