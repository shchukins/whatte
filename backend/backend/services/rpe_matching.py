"""Shared pure comparable-session policy; no database or application imports."""
from math import isfinite
from typing import Any

from backend.services.rpe_contract import RPE_SCALE_VERSION

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
