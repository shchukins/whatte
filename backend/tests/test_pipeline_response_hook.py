from backend.services import pipeline_service


def test_activity_pipeline_materializes_response_before_daily_recompute(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline_service,
        "fetch_and_store_activity_raw",
        lambda **kwargs: {
            "sport_type": "Ride",
            "name": "Steady ride",
            "start_date": "2026-08-30T06:00:00Z",
            "perceived_exertion": 7,
        },
    )
    monkeypatch.setattr(
        pipeline_service,
        "fetch_and_store_activity_streams",
        lambda **kwargs: {"streams_saved": 3},
    )
    monkeypatch.setattr(
        pipeline_service,
        "compute_and_store_activity_metrics",
        lambda **kwargs: {
            "tss": 60.0,
            "normalized_power": 180.0,
            "intensity_factor": 0.8,
        },
    )
    monkeypatch.setattr(
        pipeline_service,
        "resolve_activity_load",
        lambda **kwargs: {"load_source": "tss", "load_model_included": True},
    )
    monkeypatch.setattr(
        pipeline_service,
        "detect_and_apply_duplicate",
        lambda activity_id: {"canonical_activity_id": 42, "decision": "auto_merge"},
    )
    monkeypatch.setattr(
        pipeline_service,
        "import_strava_rpe",
        lambda **kwargs: calls.append((
            "rpe", kwargs["canonical_activity_id"],
            kwargs["activity"]["perceived_exertion"], kwargs["recompute"],
        )),
    )
    monkeypatch.setattr(
        pipeline_service,
        "compute_and_store_activity_response",
        lambda activity_id: calls.append(("response", activity_id))
        or {"ok": True, "activity_id": activity_id},
    )
    monkeypatch.setattr(
        pipeline_service,
        "recompute_after_activity_state_change",
        lambda user_id, from_date: calls.append(("daily", user_id, str(from_date)))
        or {
            "load": {"days_processed": 1},
            "fitness": {"days_processed": 1, "last_freshness_signal": 5.0},
        },
    )

    result = pipeline_service.process_activity_pipeline("user-1", 7, 99)

    assert calls == [
        ("rpe", 42, 7, False),
        ("response", 42),
        ("daily", "user-1", "2026-08-30"),
    ]
    assert result["response_metrics"] == {"ok": True, "activity_id": 42}
