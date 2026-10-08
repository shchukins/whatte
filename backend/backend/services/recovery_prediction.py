"""Reviewed deterministic day-level predictor; no DB/config imports or online fitting."""

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from backend.services.readiness_composition import (
    normalize_freshness, normalize_feeling, score_response_context,
)
from backend.services.recovery_prediction_config import baseline_prediction_config, validate_recovery_config
from backend.services.research_parameter_space import baseline_candidate_config, candidate_config_hash

STATE_VERSION = "recovery_affine_state_v1"
MIN_TRAIN_DAYS = 30
MIN_PAIRED_DAYS = 20
MIN_PAIRED_COVERAGE = 0.8
SXX_TOLERANCE = 1e-12
TARGET_SPEC = {"target_name": "next_day_recovery", "prediction_type": "point", "scale": "1-5"}


def canonical_hash(value):
    encoded = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def implementation_hash():
    names = ("recovery_prediction.py", "recovery_prediction_config.py",
             "readiness_composition.py", "research_parameter_space.py",
             "research_evaluator.py", "research_evaluator_v2.py", "research_versions.py")
    return hashlib.sha256(b"".join(Path(__file__).with_name(n).read_bytes() for n in names)).hexdigest()


def binary64_sum(values):
    # Python's built-in float sum changed in 3.12. Fixed serial binary64 addition
    # preserves the reviewed 3.11 operation order on preparation hosts as well.
    total = 0.0
    for value in values:
        total += value
    return total


def timestamp(value):
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        raise ValueError("invalid_source_timestamp") from None
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("invalid_source_timestamp")
    return result


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid_numeric_input")
    return float(value)


def replay_readiness(feature, config):
    """Same family operations/rounding as production, with explicit reviewed weights.

    Missing capability fails; proven absent sources renormalize. Manual physiology
    and recommendation thresholds never enter this readiness covariate.
    """
    if feature.get("feature_vector_version") != "daily_feature_vector_v2":
        raise ValueError("response_baseline_context_not_snapshotted")
    vector = feature.get("values", {})
    if vector.get("feature_vector_version") != "daily_feature_vector_v2":
        raise ValueError("row_feature_version_mismatch")
    cutoff = timestamp(feature["cutoff_at"])
    if timestamp(vector["cutoff_at"]) != cutoff or cutoff > timestamp(feature["captured_at"]):
        raise ValueError("invalid_feature_cutoff")
    features = vector["features"]
    def available(name, low=None, high=None):
        item = features[name]
        if item.get("availability") == "unavailable":
            if item.get("value") is not None or not item.get("reason_codes"):
                raise ValueError("invalid_missing_feature")
            return None
        if item.get("availability") != "available" or timestamp(item["available_at"]) > cutoff:
            raise ValueError("post_cutoff_feature")
        value = number(item["value"])
        if low is not None and not low <= value <= high:
            raise ValueError("feature_out_of_range")
        return value

    # Validate available evidence even when a candidate explicitly disables it.
    freshness = available("load.freshness")
    feeling = available("feeling.next_day_recovery_score", 1, 5)
    physiology = available("physiology.historical.recovery_score", 0, 100)
    replay = vector.get("response_replay_context")
    if not isinstance(replay, dict) or replay.get("context_version") != "response_replay_context_v1":
        raise ValueError("response_baseline_context_not_snapshotted")
    status = replay.get("availability")
    context = replay.get("context")
    if status == "unavailable":
        if context is not None or not replay.get("reason_codes"):
            raise ValueError("invalid_response_missingness")
    elif status == "available":
        if not isinstance(context, dict) or context.get("version") not in ("v1", "v2_rpe_1_10"):
            raise ValueError("unsupported_response_version")
        if replay.get("date_basis") != "stored_activity_date":
            raise ValueError("unsupported_response_date_basis")
        for key in ("source_available_at", "computed_at", "activity_start_at"):
            if timestamp(replay[key]) > cutoff:
                raise ValueError("post_cutoff_response")
        # Nonfinite/invalid nested metric values cannot be normalized into a score.
        for metric in context["baseline"]["metrics"].values():
            for key in ("current", "median", "deviation_pct"):
                if metric.get(key) is not None:
                    number(metric[key])
    else:
        if status == "unsupported" and replay.get("reason_codes") == ["response_as_of_state_unprovable"]:
            raise ValueError("response_as_of_state_unprovable")
        raise ValueError("unsupported_response_capability")
    response = score_response_context(context, target_date=vector["local_date"])
    response_score = response["score"] if config["response_enabled"] else None
    age = response["data"].get("scoring", {}).get("age_days")
    recency = max(0.0, min(1.0, 1 - max(age - 1, 0) / 6)) if age is not None and 0 <= age < 7 else 0.0
    response_weight = round(config["response_max_weight"] * recency, 6) if response_score is not None else 0.0
    scores = {
        "freshness": normalize_freshness(freshness),
        "response": response_score,
        "feeling": normalize_feeling(feeling) if config["feeling_enabled"] else None,
        "physiology": physiology if config["historical_physiology_enabled"] else None,
    }
    recovery_names = [n for n in ("feeling", "physiology") if scores[n] is not None]
    evidence = (config["recovery_evidence_weight"] - response_weight) / len(recovery_names) if recovery_names else 0.0
    weights = {"freshness": config["freshness_weight"] if scores["freshness"] is not None else 0.0,
               "response": response_weight, "feeling": evidence if "feeling" in recovery_names else 0.0,
               "physiology": evidence if "physiology" in recovery_names else 0.0}
    total = binary64_sum(weights.values())
    if total == 0:
        raise ValueError("no_scored_readiness_signal")
    contributions = [round((scores[n] or 0.0) * (weights[n] / total), 3) for n in scores]
    return max(0.0, min(100.0, round(binary64_sum(contributions), 1)))


def target_value(row):
    target = row["outcome"]["targets"].get("next_day_recovery", {})
    value = target.get("score")
    if target.get("status") != "available" or target.get("scale") != "1-5":
        return None
    if target.get("unit") != "training_day" or type(value) is not int or not 1 <= value <= 5:
        raise ValueError("invalid_recovery_target")
    return value


def training_pairs(dataset, fit_as_of):
    """Only train labels are read; availability times must precede the fit boundary."""
    config = baseline_prediction_config("0" * 64)
    pairs = []
    reasons = {}
    for row in sorted(dataset["partitions"]["train"], key=lambda r: r["observation_id"]):
        y = target_value(row)
        if y is None:
            continue
        target = row["outcome"]["targets"]["next_day_recovery"]
        if timestamp(target["updated_at"]) > fit_as_of:
            raise ValueError("train_label_after_fit_cutoff")
        try:
            x = replay_readiness(row["feature"], config) / 100
        except ValueError as error:
            reason = str(error)
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        pairs.append((row, x, float(y)))
    return pairs, reasons


def fit_recovery_state(dataset, *, fit_as_of):
    from backend.services.research_evaluator_v2 import validate_evaluation_dataset
    validate_evaluation_dataset(dataset=dataset, partition="train")
    users = {row["user_id"] for rows in dataset["partitions"].values() for row in rows}
    if len(users) != 1:
        raise ValueError("cross_user_dataset_unsupported")
    # Validation contributes only feature cutoff timestamps, never labels.
    fit_time = timestamp(fit_as_of)
    validation_rows = dataset["partitions"].get("validation", [])
    if not validation_rows or fit_time >= min(timestamp(r["feature"]["cutoff_at"]) for r in validation_rows):
        raise ValueError("fit_cutoff_not_before_validation")
    pairs, _ = training_pairs(dataset, fit_time)
    if len(pairs) < MIN_TRAIN_DAYS:
        raise ValueError("insufficient_train_coverage")
    x_bar = binary64_sum(x for _, x, _ in pairs) / len(pairs)
    y_bar = binary64_sum(y for _, _, y in pairs) / len(pairs)
    sxx = binary64_sum((x - x_bar) ** 2 for _, x, _ in pairs)
    if sxx <= SXX_TOLERANCE:
        raise ValueError("train_readiness_variance_insufficient")
    beta = binary64_sum((x - x_bar) * (y - y_bar) for _, x, y in pairs) / sxx
    alpha = y_bar - beta * x_bar
    number(alpha); number(beta)
    return {
        "state_version": STATE_VERSION, "fit_method": "ols_intercept_binary64_v1",
        "alpha": alpha, "beta": beta, "sample_count": len(pairs),
        "fit_as_of": fit_time.isoformat(), "dataset_hash": dataset["manifest"]["dataset_hash"],
        "train_membership_hash": canonical_hash([r["row_hash"] for r, _, _ in pairs]),
        "baseline_recipe_hash": candidate_config_hash(baseline_candidate_config()),
        "implementation_hash": implementation_hash(),
    }


def validate_state(state, config, dataset_hash):
    expected = {"state_version", "fit_method", "alpha", "beta", "sample_count", "fit_as_of",
                "dataset_hash", "train_membership_hash", "baseline_recipe_hash", "implementation_hash"}
    if not isinstance(state, dict) or set(state) != expected:
        raise ValueError("invalid_learned_state")
    if canonical_hash(state) != config["learned_state_hash"] or state["dataset_hash"] != dataset_hash:
        raise ValueError("learned_state_identity_mismatch")
    if state["state_version"] != STATE_VERSION or state["fit_method"] != "ols_intercept_binary64_v1":
        raise ValueError("unsupported_learned_state")
    if state["baseline_recipe_hash"] != candidate_config_hash(baseline_candidate_config()) or state["implementation_hash"] != implementation_hash():
        raise ValueError("learned_state_implementation_mismatch")
    if type(state["sample_count"]) is not int or state["sample_count"] < MIN_TRAIN_DAYS:
        raise ValueError("insufficient_train_coverage")
    number(state["alpha"]); number(state["beta"]); timestamp(state["fit_as_of"])


def prediction_artifact(*, observations, config, state, dataset_hash, partition):
    config = validate_recovery_config(config)
    validate_state(state, config, dataset_hash)
    predictions, reasons = [], {}
    for row in sorted(observations, key=lambda r: r["observation_id"]):
        try:
            readiness = replay_readiness(row["feature"], config)
        except ValueError as error:
            reason = str(error)
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        # A clamped point association, not a probability or synthetic fallback.
        value = max(1.0, min(5.0, state["alpha"] + state["beta"] * readiness / 100))
        predictions.append({"observation_id": row["observation_id"],
                            "targets": {"next_day_recovery": {"value": value}}})
    return {
        "prediction_schema_version": "prediction_artifact_v1",
        "candidate_id": candidate_config_hash(config), "candidate_version": config["candidate_model_version"],
        "dataset_hash": dataset_hash, "partition": partition,
        "target_specs": [TARGET_SPEC], "predictions": predictions,
    }, reasons
