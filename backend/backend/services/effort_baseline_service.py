"""Descriptive personal effort baseline; no readiness or causal interpretation."""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from backend.services.rpe_history_service import (
    MAX_CANDIDATES, MAX_MATCHES, MIN_MATCHES, VERSION as MATCHING_VERSION,
    compare_sessions, load_rpe_sessions,
)
from backend.services.rpe_service import RPE_SCALE_VERSION, RPE_SOURCES

VERSION = "personal_effort_deviation_v1"
WINDOW_DAYS = 365
# Current tables overwrite edits. These are availability guards, not an edit log.
AVAILABILITY_FIELDS = ("activity_updated_at", "metrics_computed_at",
                       "rpe_received_at", "resolution_at")
LIMITATIONS = ["interval_structure_unavailable", "small_selected_sample",
               "current_records_not_as_of_reconstruction",
               "target_metrics_may_have_been_recomputed",
               "no_causal_recovery_interpretation"]


def _valid_rpe(row: dict) -> bool:
    return (row.get("scale") == RPE_SCALE_VERSION and row.get("source") in RPE_SOURCES
            and type(row.get("rpe")) is int and 1 <= row["rpe"] <= 10)


def build_effort_deviation(target: dict, candidates: list[dict], *, computed_at: datetime) -> dict:
    """Median of 3–5 prior matches, MAD dispersion and actual minus median.

    Require current candidate evidence to predate target start, including receipt
    and recomputation time. An edit after cutoff removes the row: never substitute
    a lower-priority source or pretend its overwritten value can be reconstructed.
    The target rating is an outcome; only baseline evidence uses that cutoff.
    """
    cutoff = target.get("started_at")
    result = {
        "version": VERSION, "status": "unavailable", "actual_rpe": None,
        "expected_rpe": None, "ped": None, "sample_count": 0,
        "baseline": {"version": VERSION, "method": "median", "matching_version": MATCHING_VERSION,
                     "window_days": WINDOW_DAYS, "max_candidates": MAX_CANDIDATES,
                     "max_matches": MAX_MATCHES, "min_samples": MIN_MATCHES,
                     "scale": RPE_SCALE_VERSION, "eligible_sources": list(RPE_SOURCES)},
        "dispersion": None, "reliability": "unavailable", "comparison": None,
        "source_references": [], "actual_reference": None,
        "evidence_cutoff_at": cutoff, "computed_at": computed_at,
        "as_of_reproducible": False, "limitations": list(LIMITATIONS), "reason_codes": [],
    }
    if _valid_rpe(target):
        result.update(actual_rpe=target["rpe"], actual_reference=_reference(target))
    if cutoff is None or cutoff > computed_at:
        result["reason_codes"] = ["target_time_missing_or_future"]
        return result
    eligible = []
    for row in candidates:
        start = row.get("started_at")
        if (not start or not cutoff - timedelta(days=WINDOW_DAYS) <= start < cutoff
                or not _valid_rpe(row)
                or any(row.get(key) is None or row[key] >= cutoff for key in AVAILABILITY_FIELDS)
                or (row.get("rpe_observed_at") is not None and row["rpe_observed_at"] >= cutoff)):
            continue
        eligible.append(row)
    # Bound and order before matching, mirroring the history service's SQL policy.
    eligible.sort(key=lambda row: (row["started_at"], row["activity_id"]), reverse=True)
    matches = [match for row in eligible[:MAX_CANDIDATES]
               if (match := compare_sessions(target, row))]
    matches.sort(key=lambda row: (row["quality"], row["started_at"], row["activity_id"]), reverse=True)
    matches = matches[:MAX_MATCHES]
    result["sample_count"] = len(matches)
    result["source_references"] = [_reference(row) for row in matches]
    if len(matches) < MIN_MATCHES:
        result["reason_codes"] = ["insufficient_prior_available_comparable_sessions"]
        return result
    scores = [row["rpe"] for row in matches]
    expected = median(scores)
    # Unscaled MAD describes observed ratings; it is not a confidence interval.
    result.update(expected_rpe=expected,
                  dispersion={"method": "median_absolute_deviation", "mad": median(
                      [abs(score - expected) for score in scores]), "range": [min(scores), max(scores)]},
                  reliability="limited")
    if result["actual_rpe"] is None:
        result["reason_codes"] = ["actual_rpe_missing_or_incompatible"]
        return result
    deviation = target["rpe"] - expected
    result.update(status="available", ped=deviation,
                  comparison="above_median" if deviation > 0 else "below_median" if deviation < 0 else "at_median")
    return result


def _reference(row: dict) -> dict:
    return {key: row.get(key) for key in (
        "activity_id", "started_at", "rpe", "source", "scale", "rpe_observed_at",
        *AVAILABILITY_FIELDS, "quality",
    )}


def get_effort_deviation(user_id: str, activity_id: int) -> dict:
    target, candidates, computed_at = load_rpe_sessions(user_id, activity_id, prior_evidence=True)
    return build_effort_deviation(target, candidates, computed_at=computed_at)
