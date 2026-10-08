"""Read-only preparation gates; no fitting, prediction, audit writes or test access."""

from collections import Counter
from backend.services.recovery_prediction import (
    MIN_TRAIN_DAYS, MIN_PAIRED_DAYS, MIN_PAIRED_COVERAGE, SXX_TOLERANCE,
    binary64_sum, replay_readiness, target_value, timestamp, training_pairs,
)
from backend.services.recovery_prediction_config import baseline_prediction_config
from backend.services.research_evaluator_v2 import validate_evaluation_dataset

REPORT_VERSION = "recovery_data_readiness_v1"
REPLAY_REASONS = {
    "response_baseline_context_not_snapshotted", "row_feature_version_mismatch",
    "invalid_feature_cutoff", "invalid_missing_feature", "post_cutoff_feature",
    "feature_out_of_range", "invalid_response_missingness", "unsupported_response_version",
    "unsupported_response_date_basis", "post_cutoff_response", "invalid_numeric_input",
    "invalid_source_timestamp", "response_as_of_state_unprovable",
    "unsupported_response_capability", "no_scored_readiness_signal",
}


def _safe_reasons(counts):
    result = Counter()
    for reason, count in counts.items():
        result[reason if reason in REPLAY_REASONS else "replay_validation_failed"] += count
    return dict(result)


def recovery_data_readiness(dataset, *, fit_as_of):
    """Aggregate evidence only. Baseline replay is an upper bound on paired coverage.

    Train labels must be received by fit_as_of; validation labels never influence
    fitting (this report does not fit at all). Values and source identities stay
    private. Export exclusion metadata is diagnostic, outside the manifest hash.
    """
    report = {
        "report_version": REPORT_VERSION, "status": "invalid_dataset", "reasons": [],
        "required": {"train_days": MIN_TRAIN_DAYS, "paired_validation_days": MIN_PAIRED_DAYS,
                     "paired_validation_fraction": MIN_PAIRED_COVERAGE},
        "actual_paired_coverage": None,
    }
    # Reject test-inclusive exports even when their test list is empty.
    if (not isinstance(dataset, dict) or not isinstance(dataset.get("partitions"), dict)
            or not isinstance(dataset.get("manifest"), dict)):
        report["reasons"] = ["dataset_validation_failed"]
        return report
    if "test" in dataset["partitions"] or dataset.get("manifest", {}).get("test_access") != "withheld":
        report["reasons"] = ["test_export_not_allowed"]
        return report
    try:
        train, _, _ = validate_evaluation_dataset(dataset=dataset, partition="train")
        validation, _, _ = validate_evaluation_dataset(dataset=dataset, partition="validation")
        if len({row["user_id"] for row in train + validation}) > 1:
            raise ValueError("cross_user")
        fit_time = timestamp(fit_as_of)
        # Validate target semantics through the same function the runner uses.
        train_targets = [row for row in train if target_value(row) is not None]
        validation_targets = [row for row in validation if target_value(row) is not None]
        late = [row for row in train_targets
                if timestamp(row["outcome"]["targets"]["next_day_recovery"]["updated_at"]) > fit_time]
        late_ids = {row["observation_id"] for row in late}
        timely = [row for row in train_targets if row["observation_id"] not in late_ids]
        pairs, train_missing = training_pairs({"partitions": {"train": timely}}, fit_time)
        config = baseline_prediction_config("0" * 64)
        validation_missing = Counter()
        potential = 0
        for row in validation_targets:
            try:
                replay_readiness(row["feature"], config)
                potential += 1
            except ValueError as error:
                validation_missing[str(error)] += 1
        # Same serial binary64 operation order and tolerance as reviewed OLS;
        # only sufficient variance is exposed, never raw readiness or moments.
        mean = binary64_sum(x for _, x, _ in pairs) / len(pairs) if pairs else 0.0
        variance_ok = binary64_sum((x - mean) ** 2 for _, x, _ in pairs) > SXX_TOLERANCE
        temporal_ok = bool(validation) and fit_time < min(timestamp(r["feature"]["cutoff_at"]) for r in validation)
    except (ValueError, KeyError, TypeError, OverflowError, AttributeError):
        # Validation exceptions can embed source identifiers; keep stdout aggregate.
        report["reasons"] = ["dataset_validation_failed"]
        return report
    fraction = potential / len(validation_targets) if validation_targets else 0.0
    report.update(
        dataset_hash=dataset["manifest"]["dataset_hash"],
        split={key: dataset["manifest"]["split"][key]
               for key in ("train_start", "train_end", "validation_end", "test_end")},
        fit_as_of=fit_time.isoformat(),
        train={"canonical_days": dataset["manifest"]["canonical_day_counts"]["train"],
               "day_start_context_days": len(train), "compatible_target_days": len(train_targets),
               "missing_or_incompatible_target_days": len(train) - len(train_targets),
               "labels_after_fit_cutoff": len(late), "eligible_days": len(pairs),
               "readiness_variance_sufficient": variance_ok, "replay_missing_reasons": _safe_reasons(train_missing)},
        validation={"canonical_days": dataset["manifest"]["canonical_day_counts"]["validation"],
                    "day_start_context_days": len(validation),
                    "compatible_target_days": len(validation_targets),
                    "missing_or_incompatible_target_days": len(validation) - len(validation_targets),
                    "potential_baseline_pair_days": potential,
                    "potential_baseline_pair_fraction": fraction,
                    "replay_missing_reasons": _safe_reasons(validation_missing)},
    )
    reasons = []
    if late:
        reasons.append("train_label_after_fit_cutoff")
    if not temporal_ok:
        reasons.append("fit_cutoff_not_before_validation")
    if len(pairs) < MIN_TRAIN_DAYS:
        reasons.append("insufficient_train_coverage")
    if not variance_ok:
        reasons.append("train_readiness_variance_insufficient")
    if potential < MIN_PAIRED_DAYS or fraction < MIN_PAIRED_COVERAGE:
        reasons.append("insufficient_potential_validation_coverage")
    report.update(status="insufficient_data" if reasons else "ready_for_preparation", reasons=reasons)
    # Only fixed known reasons are printable; arbitrary unbound metadata is ignored.
    allowed = {"eligible_day_start_decision_missing", "immutable_day_start_snapshot_missing",
               "response_baseline_context_not_snapshotted"}
    exclusions = {"train": Counter(), "validation": Counter()}
    raw_exclusions = dataset["manifest"].get("excluded_observations", [])
    for item in raw_exclusions if isinstance(raw_exclusions, list) else []:
        if (isinstance(item, dict) and isinstance(item.get("partition"), str)
                and isinstance(item.get("reason"), str)
                and item["partition"] in exclusions and item["reason"] in allowed):
            exclusions[item["partition"]][item["reason"]] += 1
    report["export_exclusions_unverified"] = {key: dict(value) for key, value in exclusions.items()}
    return report
