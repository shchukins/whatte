from __future__ import annotations

import logging
from typing import Any

from backend.core.logging import log_event
from backend.schemas.healthkit import HealthSyncPayload
from backend.services.health_recovery_daily import recompute_health_recovery_daily_for_date
from backend.services.healthkit_ingest import save_healthkit_ingest_raw
from backend.services.healthkit_processing import process_latest_healthkit_raw
from backend.services.load_state_v2 import recompute_load_state_daily_v2
from backend.services.readiness_daily import recompute_readiness_daily_for_date

logger = logging.getLogger(__name__)


def _collect_affected_dates(payload: HealthSyncPayload) -> list[str]:
    dates: set[str] = set()

    for item in payload.sleepNights:
        dates.add(str(item.wakeDate))

    for item in payload.restingHeartRateDaily:
        dates.add(str(item.date))

    for item in payload.hrvSamples:
        dates.add(item.startAt.date().isoformat())

    if payload.latestWeight is not None:
        dates.add(payload.latestWeight.measuredAt.date().isoformat())

    return sorted(dates)


def _validate_pipeline_consistency(
    affected_dates: list[str],
    load_result: dict[str, Any],
    readiness_results: list[dict[str, Any]],
) -> None:
    if not affected_dates:
        return

    load_last_date = load_result.get("last_date")
    latest_affected_date = affected_dates[-1]

    if load_last_date is None or load_last_date < latest_affected_date:
        raise ValueError(
            "load_state_daily_v2 did not reach latest recovery date: "
            f"load_last_date={load_last_date}, latest_affected_date={latest_affected_date}"
        )

    readiness_by_date = {result.get("date"): result for result in readiness_results}

    for target_date in affected_dates:
        readiness_result = readiness_by_date.get(target_date)
        if not readiness_result or not readiness_result.get("ok"):
            raise ValueError(f"readiness_daily was not created for date={target_date}")

        explanation_json = readiness_result.get("explanation_json")
        if not isinstance(explanation_json, dict):
            raise ValueError(f"readiness explanation missing for date={target_date}")

        if "recovery_explanation" not in explanation_json:
            raise ValueError(
                f"readiness explanation missing recovery_explanation for date={target_date}"
            )

        if readiness_result.get("freshness") is None:
            raise ValueError(
                "freshness is missing after load recompute for date="
                f"{target_date}"
            )


def ingest_and_process_healthkit_payload(user_id: str, payload: HealthSyncPayload) -> dict[str, Any]:
    # 1. Raw ingest
    save_healthkit_ingest_raw(user_id=user_id, payload=payload)

    # 2. Latest raw -> normalized tables
    processing_result = process_latest_healthkit_raw(user_id=user_id)

    # 3. Determine affected dates from payload
    affected_dates = _collect_affected_dates(payload)
    max_affected_date = affected_dates[-1] if affected_dates else None

    recovery_results = []
    readiness_results = []

    # 4. Recompute recovery for all affected dates
    for target_date in affected_dates:
        recovery_result = recompute_health_recovery_daily_for_date(
            user_id=user_id,
            target_date=target_date,
        )
        recovery_results.append(recovery_result)

    # 5. Recompute load state after recovery so freshness is available to readiness.
    load_result = recompute_load_state_daily_v2(user_id=user_id)

    # 6. Recompute readiness for all affected dates
    for target_date in affected_dates:
        readiness_result = recompute_readiness_daily_for_date(
            user_id=user_id,
            target_date=target_date,
        )
        readiness_results.append(readiness_result)

    _validate_pipeline_consistency(
        affected_dates=affected_dates,
        load_result=load_result,
        readiness_results=readiness_results,
    )

    log_event(
        logger,
        "healthkit_payload_processed",
        user_id=user_id,
        affected_dates_count=len(affected_dates),
        sleep_count=len(payload.sleepNights),
        hrv_count=len(payload.hrvSamples),
        rhr_count=len(payload.restingHeartRateDaily),
        readiness_days_recomputed=len(readiness_results),
    )

    return {
        "ok": True,
        "user_id": user_id,
        "affected_dates": affected_dates,
        "max_affected_date": max_affected_date,
        "sleep_nights_count": len(payload.sleepNights),
        "resting_hr_count": len(payload.restingHeartRateDaily),
        "hrv_count": len(payload.hrvSamples),
        "latest_weight_included": payload.latestWeight is not None,
        "normalized": processing_result,
        "recovery_days_recomputed": len(recovery_results),
        "load_recomputed": True,
        "load_days_recomputed": load_result.get("days_processed"),
        "load_last_date": load_result.get("last_date"),
        "readiness_days_recomputed": len(readiness_results),
        "downstream_consistency_checked": True,
    }
