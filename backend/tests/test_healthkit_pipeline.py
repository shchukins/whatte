from datetime import date, datetime

import pytest

from backend.schemas.healthkit import (
    HRVSampleDTO,
    HealthSyncPayload,
    LatestWeightDTO,
    RestingHRDailyDTO,
    SleepNightDTO,
)
from backend.services import healthkit_pipeline


def test_ingest_and_process_healthkit_payload_runs_full_current_state_pipeline(monkeypatch):
    call_order: list[tuple[str, str | None]] = []

    payload = HealthSyncPayload(
        generatedAt=datetime(2026, 4, 17, 10, 0, 0),
        timezone="Europe/Moscow",
        sleepNights=[
            SleepNightDTO(
                wakeDate=date(2026, 4, 15),
                sleepStart=datetime(2026, 4, 14, 23, 0, 0),
                sleepEnd=datetime(2026, 4, 15, 7, 0, 0),
                totalSleepMinutes=480.0,
                awakeMinutes=20.0,
                coreMinutes=260.0,
                remMinutes=120.0,
                deepMinutes=100.0,
            )
        ],
        restingHeartRateDaily=[
            RestingHRDailyDTO(
                date=date(2026, 4, 16),
                bpm=52.0,
            )
        ],
        hrvSamples=[
            HRVSampleDTO(
                startAt=datetime(2026, 4, 16, 6, 30, 0),
                valueMs=64.0,
            ),
            HRVSampleDTO(
                startAt=datetime(2026, 4, 15, 6, 20, 0),
                valueMs=62.0,
            ),
        ],
        latestWeight=LatestWeightDTO(
            measuredAt=datetime(2026, 4, 16, 8, 0, 0),
            kilograms=72.5,
        ),
    )

    def fake_save_healthkit_ingest_raw(*, user_id, payload):
        call_order.append(("ingest", user_id))

    def fake_process_latest_healthkit_raw(user_id):
        call_order.append(("normalize", user_id))
        return {
            "ok": True,
            "user_id": user_id,
            "sleep_nights_processed": 1,
            "resting_hr_processed": 1,
            "hrv_processed": 2,
            "weight_processed": 1,
        }

    def fake_recompute_health_recovery_daily_for_date(user_id, target_date):
        call_order.append(("recovery", target_date))
        return {"ok": True, "date": target_date}

    def fake_recompute_load_state_daily_v2(user_id):
        call_order.append(("load", user_id))
        return {
            "ok": True,
            "user_id": user_id,
            "days_processed": 11,
            "last_date": "2026-04-16",
        }

    def fake_recompute_readiness_daily_for_date(user_id, target_date):
        call_order.append(("readiness", target_date))
        return {
            "ok": True,
            "date": target_date,
            "freshness": 8.0,
            "recovery_score_simple": 64.0,
            "explanation_json": {
                "fallback_mode": None,
                "freshness": 8.0,
                "freshness_norm": 58.0,
                "recovery_score_simple": 64.0,
                "recovery_explanation": {"method": "baseline_v2"},
            },
        }

    monkeypatch.setattr(
        healthkit_pipeline,
        "save_healthkit_ingest_raw",
        fake_save_healthkit_ingest_raw,
    )
    monkeypatch.setattr(
        healthkit_pipeline,
        "process_latest_healthkit_raw",
        fake_process_latest_healthkit_raw,
    )
    monkeypatch.setattr(
        healthkit_pipeline,
        "recompute_health_recovery_daily_for_date",
        fake_recompute_health_recovery_daily_for_date,
    )
    monkeypatch.setattr(
        healthkit_pipeline,
        "recompute_load_state_daily_v2",
        fake_recompute_load_state_daily_v2,
    )
    monkeypatch.setattr(
        healthkit_pipeline,
        "recompute_readiness_daily_for_date",
        fake_recompute_readiness_daily_for_date,
    )

    result = healthkit_pipeline.ingest_and_process_healthkit_payload(
        user_id="user-1",
        payload=payload,
    )

    assert result == {
        "ok": True,
        "user_id": "user-1",
        "affected_dates": ["2026-04-15", "2026-04-16"],
        "max_affected_date": "2026-04-16",
        "sleep_nights_count": 1,
        "resting_hr_count": 1,
        "hrv_count": 2,
        "latest_weight_included": True,
        "normalized": {
            "ok": True,
            "user_id": "user-1",
            "sleep_nights_processed": 1,
            "resting_hr_processed": 1,
            "hrv_processed": 2,
            "weight_processed": 1,
        },
        "recovery_days_recomputed": 2,
        "load_recomputed": True,
        "load_days_recomputed": 11,
        "load_last_date": "2026-04-16",
        "readiness_days_recomputed": 2,
        "downstream_consistency_checked": True,
    }

    assert call_order == [
        ("ingest", "user-1"),
        ("normalize", "user-1"),
        ("recovery", "2026-04-15"),
        ("recovery", "2026-04-16"),
        ("load", "user-1"),
        ("readiness", "2026-04-15"),
        ("readiness", "2026-04-16"),
    ]


def test_ingest_and_process_healthkit_payload_fails_when_load_does_not_reach_latest_recovery_date(monkeypatch):
    payload = HealthSyncPayload(
        generatedAt=datetime(2026, 4, 17, 10, 0, 0),
        timezone="Europe/Moscow",
        sleepNights=[
            SleepNightDTO(
                wakeDate=date(2026, 4, 16),
                sleepStart=datetime(2026, 4, 15, 23, 0, 0),
                sleepEnd=datetime(2026, 4, 16, 7, 0, 0),
                totalSleepMinutes=480.0,
                awakeMinutes=20.0,
                coreMinutes=260.0,
                remMinutes=120.0,
                deepMinutes=100.0,
            )
        ],
        restingHeartRateDaily=[],
        hrvSamples=[],
        latestWeight=None,
    )

    monkeypatch.setattr(healthkit_pipeline, "save_healthkit_ingest_raw", lambda **kwargs: None)
    monkeypatch.setattr(
        healthkit_pipeline,
        "process_latest_healthkit_raw",
        lambda user_id: {"ok": True},
    )
    monkeypatch.setattr(
        healthkit_pipeline,
        "recompute_health_recovery_daily_for_date",
        lambda user_id, target_date: {"ok": True, "date": target_date},
    )
    monkeypatch.setattr(
        healthkit_pipeline,
        "recompute_load_state_daily_v2",
        lambda user_id: {"ok": True, "days_processed": 1, "last_date": "2026-04-15"},
    )
    monkeypatch.setattr(
        healthkit_pipeline,
        "recompute_readiness_daily_for_date",
        lambda user_id, target_date: {
            "ok": True,
            "date": target_date,
            "freshness": 7.0,
            "recovery_score_simple": 63.0,
            "explanation_json": {
                "recovery_explanation": {"method": "baseline_v2"},
            },
        },
    )

    with pytest.raises(ValueError) as exc_info:
        healthkit_pipeline.ingest_and_process_healthkit_payload(
            user_id="user-1",
            payload=payload,
        )

    assert "did not reach latest recovery date" in str(exc_info.value)
