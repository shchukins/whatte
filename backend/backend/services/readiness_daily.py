from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import HTTPException

from backend.core.logging import log_event
from backend.db import get_conn
from backend.services.decision_engine import build_recommendation

logger = logging.getLogger(__name__)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_freshness(freshness: float | None) -> float | None:
    # Переводим freshness в грубую шкалу 0..100.
    # Это временная эвристика для V2, пока без probability calibration.
    if freshness is None:
        return None

    return _clamp(50.0 + freshness, 0.0, 100.0)


def _describe_readiness_status(score: float | None) -> str:
    if score is None:
        return "n/a"
    if score <= 24:
        return "Высокая усталость"
    if score <= 44:
        return "Нагрузка"
    if score <= 64:
        return "Нормальная готовность"
    if score <= 84:
        return "Хорошая готовность"
    return "Очень свежий"


def _detect_fallback_mode(
    freshness_norm: float | None,
    recovery_score_simple: float | None,
) -> str | None:
    if freshness_norm is None and recovery_score_simple is not None:
        return "recovery_only"
    if freshness_norm is not None and recovery_score_simple is None:
        return "load_only"
    return None


def recompute_readiness_daily_for_date(user_id: str, target_date: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    log_event(
        logger,
        "readiness_recompute_started",
        user_id=user_id,
        target_date=target_date,
    )

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select freshness
                    from load_state_daily_v2
                    where user_id = %s
                      and date = %s
                      and version = 'v2';
                    """,
                    (user_id, target_date),
                )
                load_row = cur.fetchone()

                cur.execute(
                    """
                    select
                        recovery_score_simple,
                        recovery_explanation_json
                    from health_recovery_daily
                    where user_id = %s
                      and date = %s;
                    """,
                    (user_id, target_date),
                )
                recovery_row = cur.fetchone()

                freshness = load_row[0] if load_row else None
                recovery_score_simple = recovery_row[0] if recovery_row else None
                recovery_explanation = recovery_row[1] if recovery_row else None

                if isinstance(recovery_explanation, str):
                    recovery_explanation = json.loads(recovery_explanation)

                if freshness is None and recovery_score_simple is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"no load or recovery data found for user_id={user_id} date={target_date}",
                    )

                freshness_norm = _normalize_freshness(freshness)

                fallback_mode = _detect_fallback_mode(
                    freshness_norm=freshness_norm,
                    recovery_score_simple=recovery_score_simple,
                )

                # V2 baseline formula:
                # readiness = 60% load-state + 40% recovery-state
                if fallback_mode == "recovery_only":
                    readiness_score_raw = recovery_score_simple
                elif fallback_mode == "load_only":
                    readiness_score_raw = freshness_norm
                else:
                    readiness_score_raw = 0.6 * freshness_norm + 0.4 * recovery_score_simple

                readiness_score = (
                    _clamp(round(readiness_score_raw, 1), 0.0, 100.0)
                    if readiness_score_raw is not None
                    else None
                )

                good_day_probability = (
                    round(readiness_score / 100.0, 3)
                    if readiness_score is not None
                    else None
                )

                status_text = _describe_readiness_status(readiness_score)

                explanation_json = {
                    "fallback_mode": fallback_mode,
                    "freshness": freshness,
                    "freshness_norm": freshness_norm,
                    "recovery_score_simple": recovery_score_simple,
                    "weights": {
                        "freshness_norm": 0.6,
                        "recovery_score_simple": 0.4,
                    },
                    "formula": "0.6 * freshness_norm + 0.4 * recovery_score_simple",
                    "recovery_explanation": recovery_explanation,
                }

                cur.execute(
                    """
                    insert into readiness_daily (
                        user_id,
                        date,
                        freshness,
                        recovery_score_simple,
                        readiness_score_raw,
                        readiness_score,
                        good_day_probability,
                        status_text,
                        explanation_json,
                        version,
                        updated_at
                    )
                    values (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'v2', now()
                    )
                    on conflict (user_id, date, version) do update set
                        freshness = excluded.freshness,
                        recovery_score_simple = excluded.recovery_score_simple,
                        readiness_score_raw = excluded.readiness_score_raw,
                        readiness_score = excluded.readiness_score,
                        good_day_probability = excluded.good_day_probability,
                        status_text = excluded.status_text,
                        explanation_json = excluded.explanation_json,
                        updated_at = now();
                    """,
                    (
                        user_id,
                        target_date,
                        freshness,
                        recovery_score_simple,
                        readiness_score_raw,
                        readiness_score,
                        good_day_probability,
                        status_text,
                        json.dumps(explanation_json),
                    ),
                )
                conn.commit()

        decision = build_recommendation(
            readiness_score=readiness_score,
            explanation=explanation_json,
        )

        result = {
            "ok": True,
            "user_id": user_id,
            "date": target_date,
            "freshness": freshness,
            "freshness_norm": freshness_norm,
            "recovery_score_simple": recovery_score_simple,
            "readiness_score_raw": readiness_score_raw,
            "readiness_score": readiness_score,
            "good_day_probability": good_day_probability,
            "status_text": status_text,
            "fallback_mode": fallback_mode,
            "explanation_json": explanation_json,
            **decision,
        }
        log_event(
            logger,
            "readiness_recompute_finished",
            user_id=user_id,
            target_date=target_date,
            readiness_score=readiness_score,
            good_day_probability=good_day_probability,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return result
    except Exception as exc:
        log_event(
            logger,
            "error",
            level=logging.ERROR,
            error_type=type(exc).__name__,
            error=str(exc),
            context="readiness_recompute",
            user_id=user_id,
            target_date=target_date,
        )
        raise
