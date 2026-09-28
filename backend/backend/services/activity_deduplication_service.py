from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from backend.db import get_conn


DETECTION_VERSION = "indoor_mywhoosh_garmin_v1"
MIN_OVERLAP_RATIO = 0.80
MAX_DURATION_DIFFERENCE_RATIO = 0.15
MAX_START_DIFFERENCE_SECONDS = 10 * 60
HIGH_CONFIDENCE_THRESHOLD = 0.85
CANDIDATE_ACTUAL_TIME_WINDOW = timedelta(hours=24)

CYCLING_ACTIVITY_TYPES = {
    "ebikeride",
    "handcycle",
    "mountainbikeride",
    "ride",
    "velomobileride",
    "virtualride",
}
SOURCE_MYWHOOSH = "mywhoosh"
SOURCE_VIRTUAL_RIDE = "virtual_ride"
SOURCE_GARMIN = "garmin"
SOURCE_UNKNOWN = "unknown"

DELIVERY_TRAINING_PROCESSED = "training_processed"
DELIVERY_POST_RIDE_RPE = "post_ride_rpe"


def _as_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _metadata_text(raw_json: dict[str, Any]) -> str:
    strong_keys = (
        "device_name",
        "external_id",
        "upload_id",
        "upload_id_str",
        "app_name",
        "source",
    )
    values = [str(raw_json.get(key) or "") for key in strong_keys]
    upload = raw_json.get("upload")
    if isinstance(upload, dict):
        values.extend(str(value or "") for value in upload.values())
    return " ".join(values).lower()


def identify_activity_source(activity: dict[str, Any]) -> dict[str, Any]:
    """Classify recording source using metadata first and title only as fallback."""
    raw_json = _as_json_object(activity.get("raw_json"))
    metadata = _metadata_text(raw_json)
    title = str(activity.get("name") or raw_json.get("name") or "").lower()

    if "mywhoosh" in metadata or "my whoosh" in metadata:
        return {"source": SOURCE_MYWHOOSH, "reason": "upload_metadata"}
    if "garmin" in metadata:
        return {"source": SOURCE_GARMIN, "reason": "device_or_upload_metadata"}
    if "mywhoosh" in title or "my whoosh" in title:
        return {"source": SOURCE_MYWHOOSH, "reason": "activity_name_fallback"}
    if "garmin" in title:
        return {"source": SOURCE_GARMIN, "reason": "activity_name_fallback"}
    activity_type = _activity_type(activity)
    trainer = activity.get("trainer")
    if trainer is None:
        trainer = raw_json.get("trainer")
    if activity_type == "virtualride" and trainer is True:
        return {
            "source": SOURCE_VIRTUAL_RIDE,
            "reason": "virtual_ride_trainer_fallback",
        }
    return {"source": SOURCE_UNKNOWN, "reason": "no_source_signal"}


def _activity_type(activity: dict[str, Any]) -> str:
    raw_json = _as_json_object(activity.get("raw_json"))
    return str(
        activity.get("activity_type")
        or raw_json.get("sport_type")
        or raw_json.get("type")
        or ""
    ).lower()


def _duration_seconds(activity: dict[str, Any]) -> int:
    return int(activity.get("elapsed_time_s") or activity.get("moving_time_s") or 0)


def _is_manually_separate(activity: dict[str, Any], other_activity_id: int) -> bool:
    return (
        activity.get("deduplication_manual_override") == "separate"
        and activity.get("duplicate_candidate_activity_id") == other_activity_id
    )


def evaluate_duplicate_pair(
    new_activity: dict[str, Any],
    candidate_activity: dict[str, Any],
) -> dict[str, Any]:
    new_id = int(new_activity["strava_activity_id"])
    candidate_id = int(candidate_activity["strava_activity_id"])
    reasons: list[str] = []

    if _is_manually_separate(new_activity, candidate_id) or _is_manually_separate(
        candidate_activity, new_id
    ):
        return {
            "candidate_activity_id": candidate_id,
            "canonical_activity_id": None,
            "duplicate_activity_id": None,
            "confidence": 0.0,
            "reasons": ["manual_separate_override"],
            "decision": "separate",
        }

    if _activity_type(new_activity) not in CYCLING_ACTIVITY_TYPES or _activity_type(
        candidate_activity
    ) not in CYCLING_ACTIVITY_TYPES:
        reasons.append("not_both_cycling")

    new_source = identify_activity_source(new_activity)
    candidate_source = identify_activity_source(candidate_activity)
    source_pair_is_supported = (
        SOURCE_GARMIN in {new_source["source"], candidate_source["source"]}
        and any(
            source in {SOURCE_MYWHOOSH, SOURCE_VIRTUAL_RIDE}
            for source in {new_source["source"], candidate_source["source"]}
        )
    )
    if not source_pair_is_supported:
        reasons.append("source_pair_not_mywhoosh_garmin")

    new_start = new_activity.get("start_date")
    candidate_start = candidate_activity.get("start_date")
    new_duration = _duration_seconds(new_activity)
    candidate_duration = _duration_seconds(candidate_activity)
    if (
        not isinstance(new_start, datetime)
        or not isinstance(candidate_start, datetime)
        or new_duration <= 0
        or candidate_duration <= 0
    ):
        reasons.append("missing_time_interval")
        overlap_ratio = 0.0
        duration_difference_ratio = 1.0
        start_difference_seconds = float("inf")
    else:
        new_end = new_start + timedelta(seconds=new_duration)
        candidate_end = candidate_start + timedelta(seconds=candidate_duration)
        overlap_seconds = max(
            0.0,
            (min(new_end, candidate_end) - max(new_start, candidate_start)).total_seconds(),
        )
        overlap_ratio = overlap_seconds / min(new_duration, candidate_duration)
        duration_difference_ratio = (
            abs(new_duration - candidate_duration) / max(new_duration, candidate_duration)
        )
        start_difference_seconds = abs((new_start - candidate_start).total_seconds())

        if overlap_ratio < MIN_OVERLAP_RATIO:
            reasons.append("overlap_below_threshold")
        if duration_difference_ratio > MAX_DURATION_DIFFERENCE_RATIO:
            reasons.append("duration_difference_above_threshold")
        if start_difference_seconds > MAX_START_DIFFERENCE_SECONDS:
            reasons.append("start_difference_above_threshold")

    confidence = round(
        0.50
        + 0.30 * min(1.0, overlap_ratio)
        + 0.15 * max(0.0, 1.0 - duration_difference_ratio)
        + 0.05
        * max(
            0.0,
            1.0 - start_difference_seconds / MAX_START_DIFFERENCE_SECONDS,
        ),
        4,
    )
    if reasons or confidence < HIGH_CONFIDENCE_THRESHOLD:
        if confidence < HIGH_CONFIDENCE_THRESHOLD:
            reasons.append("confidence_below_threshold")
        return {
            "candidate_activity_id": candidate_id,
            "canonical_activity_id": None,
            "duplicate_activity_id": None,
            "confidence": confidence,
            "reasons": reasons,
            "decision": "no_match",
        }

    canonical_activity_id = (
        new_id
        if new_source["source"] in {SOURCE_MYWHOOSH, SOURCE_VIRTUAL_RIDE}
        else candidate_id
    )
    duplicate_activity_id = (
        candidate_id if canonical_activity_id == new_id else new_id
    )
    reasons.extend(
        [
            f"source_pair:{new_source['source']}:{candidate_source['source']}",
            f"source_signals:{new_source['reason']}:{candidate_source['reason']}",
            f"overlap_ratio:{overlap_ratio:.4f}",
            f"duration_difference_ratio:{duration_difference_ratio:.4f}",
            f"start_difference_seconds:{start_difference_seconds:.0f}",
        ]
    )
    return {
        "candidate_activity_id": candidate_id,
        "canonical_activity_id": canonical_activity_id,
        "duplicate_activity_id": duplicate_activity_id,
        "confidence": confidence,
        "reasons": reasons,
        "decision": "auto_merge",
    }


_ACTIVITY_SELECT = """
    select
        strava_activity_id,
        user_id,
        activity_type,
        name,
        start_date,
        moving_time_s,
        elapsed_time_s,
        trainer,
        raw_json,
        duplicate_of_activity_id,
        is_excluded,
        exclusion_reason,
        deduplication_manual_override,
        duplicate_candidate_activity_id
    from strava_activity_raw
"""


def _activity_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "strava_activity_id",
        "user_id",
        "activity_type",
        "name",
        "start_date",
        "moving_time_s",
        "elapsed_time_s",
        "trainer",
        "raw_json",
        "duplicate_of_activity_id",
        "is_excluded",
        "exclusion_reason",
        "deduplication_manual_override",
        "duplicate_candidate_activity_id",
    )
    return dict(zip(keys, row))


def detect_duplicate_candidate(new_activity_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _ACTIVITY_SELECT + " where strava_activity_id = %s;",
                (new_activity_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"activity not found: {new_activity_id}")
            new_activity = _activity_from_row(row)

            start_date = new_activity.get("start_date")
            if not isinstance(start_date, datetime):
                return {
                    "candidate_activity_id": None,
                    "canonical_activity_id": None,
                    "duplicate_activity_id": None,
                    "confidence": 0.0,
                    "reasons": ["missing_start_date"],
                    "decision": "no_match",
                }

            cur.execute(
                _ACTIVITY_SELECT
                + """
                  where user_id = %s
                    and strava_activity_id <> %s
                    and is_deleted = false
                    and start_date between %s and %s
                  order by abs(extract(epoch from (start_date - %s))), strava_activity_id;
                """,
                (
                    new_activity["user_id"],
                    new_activity_id,
                    start_date - CANDIDATE_ACTUAL_TIME_WINDOW,
                    start_date + CANDIDATE_ACTUAL_TIME_WINDOW,
                    start_date,
                ),
            )
            candidates = [_activity_from_row(candidate) for candidate in cur.fetchall()]

    evaluated = [
        evaluate_duplicate_pair(new_activity, candidate) for candidate in candidates
    ]
    matches = [result for result in evaluated if result["decision"] == "auto_merge"]
    if not matches:
        return {
            "candidate_activity_id": None,
            "canonical_activity_id": None,
            "duplicate_activity_id": None,
            "confidence": max(
                (result["confidence"] for result in evaluated),
                default=0.0,
            ),
            "reasons": ["no_high_confidence_candidate"],
            "decision": "no_match",
        }
    return sorted(
        matches,
        key=lambda result: (-result["confidence"], result["candidate_activity_id"]),
    )[0]


def _transfer_canonical_metadata(
    cur: Any,
    *,
    canonical_activity_id: int,
    duplicate_activity_id: int,
) -> None:
    from backend.services.rpe_service import refresh_rpe_resolution

    cur.execute(
        """
        update activity_rpe_observation observation
        set canonical_activity_id = %s
        where observation.canonical_activity_id = %s
          and not exists (
              select 1 from activity_rpe_observation existing
              where existing.canonical_activity_id = %s
                and existing.source = observation.source
          );
        """,
        (canonical_activity_id, duplicate_activity_id, canonical_activity_id),
    )
    cur.execute(
        "select user_id from strava_activity_raw where strava_activity_id = %s;",
        (canonical_activity_id,),
    )
    owner = cur.fetchone()
    if owner:
        refresh_rpe_resolution(
            cur, user_id=owner[0], activity_id=canonical_activity_id
        )
    cur.execute(
        """
        update activity_subjective_feedback
        set canonical_activity_id = %s,
            updated_at = now()
        where canonical_activity_id = %s
          and not exists (
              select 1
              from activity_subjective_feedback existing
              where existing.canonical_activity_id = %s
                and existing.feedback_type = activity_subjective_feedback.feedback_type
          );
        """,
        (canonical_activity_id, duplicate_activity_id, canonical_activity_id),
    )
    cur.execute(
        """
        insert into activity_delivery_log (
            user_id,
            activity_id,
            delivery_type,
            delivery_status,
            telegram_message_id,
            payload_json,
            created_at,
            updated_at
        )
        select
            user_id,
            %s,
            delivery_type,
            delivery_status,
            telegram_message_id,
            payload_json,
            created_at,
            now()
        from activity_delivery_log
        where activity_id = %s
        on conflict (activity_id, delivery_type) do nothing;
        """,
        (canonical_activity_id, duplicate_activity_id),
    )
    cur.execute(
        "delete from activity_delivery_log where activity_id = %s;",
        (duplicate_activity_id,),
    )


def apply_duplicate_decision(result: dict[str, Any]) -> bool:
    if result.get("decision") != "auto_merge":
        return False
    canonical_id = int(result["canonical_activity_id"])
    duplicate_id = int(result["duplicate_activity_id"])
    reason_json = json.dumps(result["reasons"])

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select strava_activity_id
                from strava_activity_raw
                where strava_activity_id in (%s, %s)
                for update;
                """,
                (canonical_id, duplicate_id),
            )
            if len(cur.fetchall()) != 2:
                raise ValueError("canonical or duplicate activity disappeared")

            cur.execute(
                """
                update strava_activity_raw
                set duplicate_of_activity_id = null,
                    is_excluded = case
                        when exclusion_reason = 'automatic_duplicate' then false
                        else is_excluded
                    end,
                    exclusion_reason = case
                        when exclusion_reason = 'automatic_duplicate' then null
                        else exclusion_reason
                    end,
                    duplicate_candidate_activity_id = %s,
                    updated_at = now()
                where strava_activity_id = %s;
                """,
                (duplicate_id, canonical_id),
            )
            cur.execute(
                """
                update strava_activity_raw
                set duplicate_of_activity_id = %s,
                    is_excluded = true,
                    exclusion_reason = 'automatic_duplicate',
                    duplicate_confidence = %s,
                    duplicate_reason = %s::jsonb,
                    duplicate_detected_at = now(),
                    duplicate_detection_version = %s,
                    duplicate_candidate_activity_id = %s,
                    updated_at = now()
                where strava_activity_id = %s
                  and deduplication_manual_override is distinct from 'separate';
                """,
                (
                    canonical_id,
                    result["confidence"],
                    reason_json,
                    DETECTION_VERSION,
                    canonical_id,
                    duplicate_id,
                ),
            )
            changed = cur.rowcount > 0
            if changed:
                _transfer_canonical_metadata(
                    cur,
                    canonical_activity_id=canonical_id,
                    duplicate_activity_id=duplicate_id,
                )
            conn.commit()
    return changed


def detect_and_apply_duplicate(new_activity_id: int) -> dict[str, Any]:
    result = detect_duplicate_candidate(new_activity_id)
    result["state_changed"] = apply_duplicate_decision(result)
    return result


def resolve_canonical_activity(activity_id: int) -> int:
    visited: set[int] = set()
    current = activity_id
    with get_conn() as conn:
        with conn.cursor() as cur:
            while True:
                if current in visited:
                    raise ValueError(f"duplicate cycle detected for activity_id={activity_id}")
                visited.add(current)
                cur.execute(
                    """
                    select duplicate_of_activity_id, deduplication_manual_override
                    from strava_activity_raw
                    where strava_activity_id = %s;
                    """,
                    (current,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"activity not found: {current}")
                duplicate_of, manual_override = row
                if manual_override == "separate" or duplicate_of is None:
                    return current
                current = int(duplicate_of)


def get_activity_deduplication_state(activity_id: int) -> dict[str, Any]:
    canonical_id = resolve_canonical_activity(activity_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, is_excluded, exclusion_reason
                from strava_activity_raw
                where strava_activity_id = %s;
                """,
                (activity_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError(f"activity not found: {activity_id}")
    return {
        "activity_id": activity_id,
        "canonical_activity_id": canonical_id,
        "user_id": row[0],
        "is_excluded": bool(row[1]),
        "exclusion_reason": row[2],
    }


def claim_activity_delivery(
    *,
    user_id: str,
    canonical_activity_id: int,
    delivery_type: str,
) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into activity_delivery_log (
                    user_id,
                    activity_id,
                    delivery_type,
                    delivery_status
                )
                values (%s, %s, %s, 'claimed')
                on conflict (activity_id, delivery_type) do nothing
                returning id;
                """,
                (user_id, canonical_activity_id, delivery_type),
            )
            claimed = cur.fetchone() is not None
            conn.commit()
    return claimed


def mark_activity_delivery_sent(
    *,
    canonical_activity_id: int,
    delivery_type: str,
    telegram_message_id: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update activity_delivery_log
                set delivery_status = 'sent',
                    telegram_message_id = %s,
                    payload_json = %s::jsonb,
                    updated_at = now()
                where activity_id = %s
                  and delivery_type = %s;
                """,
                (
                    telegram_message_id,
                    json.dumps(payload or {}),
                    canonical_activity_id,
                    delivery_type,
                ),
            )
            conn.commit()


def release_activity_delivery_claim(
    *,
    canonical_activity_id: int,
    delivery_type: str,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from activity_delivery_log
                where activity_id = %s
                  and delivery_type = %s
                  and delivery_status = 'claimed';
                """,
                (canonical_activity_id, delivery_type),
            )
            conn.commit()


def recompute_after_activity_state_change(
    user_id: str,
    from_date: date | None,
    *,
    through_date: str | None = None,
) -> dict[str, Any]:
    from backend.services.fitness_service import recompute_fitness_state
    from backend.services.load_service import recompute_daily_load_all
    from backend.services.load_state_v2 import recompute_load_state_daily_v2
    from backend.services.readiness_daily import recompute_readiness_daily_for_date

    load_result = recompute_daily_load_all(user_id)
    fitness_result = recompute_fitness_state(user_id)
    # Profile corrections must propagate across subsequent rest days as well.
    load_state_result = (
        recompute_load_state_daily_v2(user_id, through_date=through_date)
        if through_date is not None
        else recompute_load_state_daily_v2(user_id)
    )
    if from_date is None:
        return {
            "load": load_result,
            "fitness": fitness_result,
            "load_state": load_state_result,
            "readiness_dates": [],
        }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select date
                from load_state_daily_v2
                where user_id = %s
                  and date >= %s
                  and version = 'v2'
                order by date;
                """,
                (user_id, from_date),
            )
            dates = [row[0] for row in cur.fetchall()]
    for target_date in dates:
        recompute_readiness_daily_for_date(user_id, str(target_date))
    return {
        "load": load_result,
        "fitness": fitness_result,
        "load_state": load_state_result,
        "readiness_dates": [str(target_date) for target_date in dates],
    }


def set_manual_exclusion(activity_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update strava_activity_raw
                set is_excluded = true,
                    exclusion_reason = 'manual_exclusion',
                    deduplication_manual_override = 'exclude',
                    updated_at = now()
                where strava_activity_id = %s
                returning user_id, date(start_date);
                """,
                (activity_id,),
            )
            row = cur.fetchone()
            conn.commit()
    if row is None:
        raise ValueError(f"activity not found: {activity_id}")
    recompute_after_activity_state_change(row[0], row[1])
    return get_activity_deduplication_state(activity_id)


def mark_activities_separate(activity_id: int) -> dict[str, Any]:
    canonical_id = resolve_canonical_activity(activity_id)
    if canonical_id == activity_id:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select duplicate_candidate_activity_id
                    from strava_activity_raw
                    where strava_activity_id = %s;
                    """,
                    (activity_id,),
                )
                row = cur.fetchone()
        other_id = int(row[0]) if row and row[0] is not None else None
    else:
        other_id = canonical_id
    if other_id is None:
        raise ValueError("activity has no deduplication candidate")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update strava_activity_raw
                set duplicate_of_activity_id = null,
                    is_excluded = false,
                    exclusion_reason = null,
                    duplicate_candidate_activity_id = case
                        when strava_activity_id = %s then %s
                        else %s
                    end,
                    deduplication_manual_override = 'separate',
                    updated_at = now()
                where strava_activity_id in (%s, %s)
                returning user_id, date(start_date);
                """,
                (activity_id, other_id, activity_id, activity_id, other_id),
            )
            rows = cur.fetchall()
            conn.commit()
    if not rows:
        raise ValueError(f"activity not found: {activity_id}")
    earliest = min((row[1] for row in rows if row[1] is not None), default=None)
    recompute_after_activity_state_change(rows[0][0], earliest)
    return get_activity_deduplication_state(activity_id)


def restore_manual_exclusion(activity_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update strava_activity_raw
                set is_excluded = false,
                    exclusion_reason = null,
                    deduplication_manual_override = null,
                    updated_at = now()
                where strava_activity_id = %s
                  and deduplication_manual_override = 'exclude'
                  and duplicate_of_activity_id is null
                returning user_id, date(start_date);
                """,
                (activity_id,),
            )
            row = cur.fetchone()
            conn.commit()
    if row is None:
        raise ValueError("activity cannot be restored while it is an automatic duplicate")
    recompute_after_activity_state_change(row[0], row[1])
    return get_activity_deduplication_state(activity_id)
