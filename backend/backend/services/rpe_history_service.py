"""Read-only personal RPE context; never predicts or writes a rating."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

from fastapi import HTTPException

from backend.db import get_conn
from backend.services.rpe_service import RPE_SCALE_VERSION

from backend.services.rpe_matching import (
    VERSION, MAX_CANDIDATES, MAX_MATCHES, MIN_MATCHES, DURATION_TOLERANCE,
    IF_TOLERANCE, NP_TOLERANCE, FTP_TOLERANCE, VI_TOLERANCE, MIN_QUALITY, compare_sessions,
)

FIELDS = ("activity_id", "user_id", "sport", "started_at", "duration_s",
          "np_w", "if", "tss", "vi", "rpe", "source", "scale", "activity_updated_at", "metrics_computed_at",
          "rpe_received_at", "resolution_at", "rpe_observed_at")

def build_context(target: dict, candidates: list[dict]) -> dict:
    matches = [match for row in candidates if (match := compare_sessions(target, row))]
    matches.sort(key=lambda row: (row["quality"], row["started_at"], row["activity_id"]), reverse=True)
    matches = matches[:MAX_MATCHES]
    result = {"version": VERSION, "status": "insufficient_data", "matches": [],
              "count": 0, "median": None, "range": None,
              "reason_codes": ["insufficient_comparable_power_sessions"],
              "target_metrics": {key: target.get(key) for key in ("duration_s", "np_w", "if", "tss", "vi")}}
    if len(matches) >= MIN_MATCHES:
        scores = [row["rpe"] for row in matches]
        result.update(status="available", matches=matches, count=len(matches),
                      median=median(scores), range=[min(scores), max(scores)], reason_codes=[])
    return result


# Only normalized metrics and the effective observation's original scale/source.
_SELECT = """
    select r.strava_activity_id, r.user_id, r.activity_type, r.start_date,
           coalesce(m.moving_time_s, m.duration_s), m.normalized_power,
           m.intensity_factor, m.tss, m.variability_index,
           er.effective_score, er.effective_source, obs.scale_version,
           r.updated_at, m.computed_at, obs.received_at, er.resolved_at, obs.observed_at
    from strava_activity_raw r
    left join activity_metrics m on m.strava_activity_id = r.strava_activity_id
      and m.user_id = r.user_id and m.version = 'v1'
    left join activity_rpe_resolution er on er.canonical_activity_id = r.strava_activity_id
      and er.user_id = r.user_id
    left join activity_rpe_observation obs on obs.canonical_activity_id = r.strava_activity_id
      and obs.user_id = r.user_id and obs.source = er.effective_source
      and obs.score = er.effective_score
    where r.user_id = %s and r.is_deleted = false and r.is_excluded = false
      and r.duplicate_of_activity_id is null
"""


def get_rpe_history(user_id: str, activity_id: int) -> dict:
    target, candidates, _ = load_rpe_sessions(user_id, activity_id)
    return build_context(target, candidates)


def load_rpe_sessions(user_id: str, activity_id: int, *, prior_evidence: bool = False) -> tuple:
    """Load owned current records; PED additionally gates availability before LIMIT."""
    computed_at = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT + " and r.strava_activity_id = %s", (user_id, activity_id))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, "Тренировка не найдена")
            target = dict(zip(FIELDS, row))
            availability_sql = ""
            availability_params = ()
            if prior_evidence:
                availability_sql = """
                    and r.updated_at < %s and m.computed_at < %s
                    and obs.received_at < %s and er.resolved_at < %s
                    and (obs.observed_at is null or obs.observed_at < %s)
                """
                availability_params = (target["started_at"],) * 5
            cur.execute(_SELECT + """
                and r.strava_activity_id <> %s and r.activity_type = %s
                and r.start_date < %s and r.start_date <= now()
                and r.start_date >= %s - interval '365 days'
                and obs.scale_version = %s and er.effective_score between 1 and 10
                """ + availability_sql + " order by r.start_date desc, r.strava_activity_id desc limit %s",
                (user_id, activity_id, target["sport"], target["started_at"],
                 target["started_at"], RPE_SCALE_VERSION, *availability_params, MAX_CANDIDATES))
            return target, [dict(zip(FIELDS, row)) for row in cur.fetchall()], computed_at
