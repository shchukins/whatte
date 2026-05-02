from backend.services.decision_engine import build_recommendation


def test_build_recommendation_maps_recovery_zone():
    result = build_recommendation(
        readiness_score=39.9,
        explanation={
            "freshness_norm": 42.0,
            "recovery_score_simple": 35.0,
            "fallback_mode": None,
        },
    )

    assert result["recommendation"] == "recovery"
    assert "39.9/100" in result["reason"]
    assert "Freshness is available at 42/100" in result["reason"]
    assert "Recovery is available at 35/100" in result["reason"]


def test_build_recommendation_maps_endurance_boundaries():
    assert (
        build_recommendation(readiness_score=40.0, explanation={})["recommendation"]
        == "endurance"
    )
    assert (
        build_recommendation(readiness_score=59.9, explanation={})["recommendation"]
        == "endurance"
    )


def test_build_recommendation_maps_moderate_boundaries():
    assert (
        build_recommendation(readiness_score=60.0, explanation={})["recommendation"]
        == "moderate"
    )
    assert (
        build_recommendation(readiness_score=75.0, explanation={})["recommendation"]
        == "moderate"
    )


def test_build_recommendation_maps_high_intensity_zone():
    result = build_recommendation(
        readiness_score=75.1,
        explanation={
            "freshness_norm": 84.0,
            "recovery_score_simple": 80.0,
            "fallback_mode": None,
        },
    )

    assert result["recommendation"] == "high_intensity"
    assert result["reason"].endswith("Recommendation is high_intensity.")


def test_build_recommendation_mentions_recovery_only_fallback():
    result = build_recommendation(
        readiness_score=66.4,
        explanation={
            "fallback_mode": "recovery_only",
            "freshness_norm": None,
            "recovery_score_simple": 66.4,
        },
    )

    assert result["recommendation"] == "moderate"
    assert "Recovery is available at 66.4/100" in result["reason"]
    assert "Load context is missing" in result["reason"]


def test_build_recommendation_mentions_load_only_fallback():
    result = build_recommendation(
        readiness_score=62.5,
        explanation={
            "fallback_mode": "load_only",
            "freshness_norm": 62.5,
            "recovery_score_simple": None,
        },
    )

    assert result["recommendation"] == "moderate"
    assert "Freshness is available at 62.5/100" in result["reason"]
    assert "Recovery context is missing" in result["reason"]
