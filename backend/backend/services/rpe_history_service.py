"""Read-only personal RPE context; never predicts or writes a rating."""
from __future__ import annotations

from math import isfinite
from statistics import median
from typing import Any

from fastapi import HTTPException

from backend.db import get_conn
from backend.services.rpe_service import RPE_SCALE_VERSION

VERSION = "rpe_history_v1"
MAX_CANDIDATES = 200
MAX_MATCHES = 5
MIN_MATCHES = 3
# Conservative eligibility gates, not physiological equivalence claims.
DURATION_TOLERANCE = 0.25
IF_TOLERANCE = 0.12
NP_TOLERANCE = 0.20
FTP_TOLERANCE = 0.15
VI_TOLERANCE = 0.10
MIN_QUALITY = 0.65
FIELDS = ("activity_id", "user_id", "sport", "started_at", "duration_s",
          "np_w", "if", "tss", "vi", "rpe", "source", "scale")


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def compare_sessions(target: dict, candidate: dict) -> dict | None:
    """Gate sport/time/scale first, then rank duration, relative effort and shape.

    NP and inferred historical FTP are gates only; TSS is display-only because
    duration/IF already explain it. VI is a coarse shape proxy, never intervals.
    Missing power/VI yields no guidance rather than a duration-only comparison.
    """
    if (candidate["activity_id"] == target["activity_id"]
            or candidate["user_id"] != target["user_id"]
            or candidate["sport"] != target["sport"]
            or target["sport"] not in {"Ride", "VirtualRide"}
            or not candidate["started_at"] or not target["started_at"]
            or candidate["started_at"] >= target["started_at"]
            or candidate["scale"] != RPE_SCALE_VERSION
            or type(candidate["rpe"]) is not int or not 1 <= candidate["rpe"] <= 10):
        return None
    if not all(_positive(row.get(key)) for row in (target, candidate)
               for key in ("duration_s", "np_w", "if", "vi")):
        return None
    duration_delta = abs(candidate["duration_s"] / target["duration_s"] - 1)
    if_delta = abs(candidate["if"] - target["if"])
    np_delta = abs(candidate["np_w"] / target["np_w"] - 1)
    vi_delta = abs(candidate["vi"] - target["vi"])
    ftp_delta = abs((candidate["np_w"] / candidate["if"]) /
                    (target["np_w"] / target["if"]) - 1)
    if (duration_delta > DURATION_TOLERANCE or if_delta > IF_TOLERANCE
            or np_delta > NP_TOLERANCE or ftp_delta > FTP_TOLERANCE
            or vi_delta > VI_TOLERANCE):
        return None
    # A weighted distance avoids counting NP/IF/TSS as three independent votes.
    quality = 1 - (0.4 * duration_delta / DURATION_TOLERANCE
                   + 0.4 * if_delta / IF_TOLERANCE + 0.2 * vi_delta / VI_TOLERANCE)
    if quality < MIN_QUALITY:
        return None
    return {**candidate, "quality": round(quality, 6), "match_quality": "reduced",
            "reasons": ["same_sport", "similar_duration", "similar_relative_intensity",
                        "similar_power_variability"],
            "limitations": ["interval_structure_unavailable"],
            "historical_ftp_w": candidate["np_w"] / candidate["if"]}


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
           er.effective_score, er.effective_source, obs.scale_version
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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT + " and r.strava_activity_id = %s", (user_id, activity_id))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, "Тренировка не найдена")
            target = dict(zip(FIELDS, row))
            cur.execute(_SELECT + """
                and r.strava_activity_id <> %s and r.activity_type = %s
                and r.start_date < %s and r.start_date <= now()
                and r.start_date >= %s - interval '365 days'
                and obs.scale_version = %s and er.effective_score between 1 and 10
                order by r.start_date desc, r.strava_activity_id desc limit %s
                """, (user_id, activity_id, target["sport"], target["started_at"],
                      target["started_at"], RPE_SCALE_VERSION, MAX_CANDIDATES))
            return build_context(target, [dict(zip(FIELDS, row)) for row in cur.fetchall()])
