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
