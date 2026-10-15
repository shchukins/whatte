"""Offline PED study on frozen day datasets; never imported by production paths."""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
import math
import random
from statistics import mean

from backend.services.effort_deviation_core import build_effort_deviation, AVAILABILITY_FIELDS
from backend.services.recovery_prediction import (
    canonical_hash, timestamp, number, replay_readiness, target_value,
    MIN_TRAIN_DAYS, MIN_PAIRED_DAYS, MIN_PAIRED_COVERAGE, TARGET_SPEC, binary64_sum,
)
from backend.services.recovery_prediction_config import baseline_prediction_config
from backend.services.research_evaluator_v2 import validate_evaluation_dataset, evaluate_research_candidate

VERSION = "ped_research_v1"
SNAPSHOT_VERSION = "ped_research_snapshot_v1"
VARIANTS = ("latest", "rolling", "persistent")
ABLATIONS = ("none", "response", "feeling", "physiology")
# Research design constants, not clinical thresholds or production parameters.
WINDOW_DAYS = 7
MIN_ROLLING = 3
BOOTSTRAPS = 1000
BLOCK_DAYS = 7


def validate_snapshots(evidence):
    """A prospective capture must freeze the complete matching inputs, not current PED.

    Caller supplies private, trusted immutable exports. Hashes prove integrity,
    not timestamp authenticity; backdated captures are outside this contract.
    """
    if evidence.get("version") != SNAPSHOT_VERSION or not isinstance(evidence.get("snapshots"), list):
        raise ValueError("unsupported_ped_snapshot_contract")
    result = []
    for original in evidence["snapshots"]:
        state = {k: v for k, v in original.items() if k != "snapshot_hash"}
        if canonical_hash(state) != original.get("snapshot_hash"):
            raise ValueError("ped_snapshot_hash_invalid")
        item = deepcopy(state)
        captured = timestamp(item["captured_at"])
        computed = timestamp(item["computed_at"])
        target = item["target"]
        user = target["user_id"]
        if item.get("as_of_status") != "prospective_capture" or user != item["user_id"]:
            raise ValueError("ped_as_of_state_unprovable")
        end = timestamp(item["completed_at"])
        start = timestamp(target["started_at"])
        if not start < end <= computed <= captured:
            raise ValueError("ped_completion_boundary_invalid")
        for row in [target, *item["candidates"]]:
            if row["user_id"] != user:
                raise ValueError("cross_user_ped_evidence")
            for key in ("started_at", *AVAILABILITY_FIELDS, "rpe_observed_at"):
                row[key] = timestamp(row[key]) if row.get(key) is not None else None
        if any(target[k] is None or target[k] > computed for k in AVAILABILITY_FIELDS):
            raise ValueError("ped_target_evidence_after_capture")
        if target.get("rpe_observed_at") and target["rpe_observed_at"] > computed:
            raise ValueError("ped_target_evidence_after_capture")
        candidate_ids = [r["activity_id"] for r in item["candidates"]]
        if len(candidate_ids) != len(set(candidate_ids)) or len(candidate_ids) > 200:
            raise ValueError("duplicate_or_unbounded_ped_candidates")
        ped = build_effort_deviation(target, item["candidates"], computed_at=computed)
        result.append({"user_id": user, "activity_id": target["activity_id"],
                       "started_at": start, "captured_at": captured,
                       "ped": ped["ped"], "snapshot_hash": original["snapshot_hash"]})
    if len({(s["user_id"], s["activity_id"]) for s in result}) != len(result):
        raise ValueError("duplicate_ped_snapshot")
    return result


def covariates(row, snapshots):
    cutoff = timestamp(row["feature"]["cutoff_at"])
    eligible = [s for s in snapshots if s["user_id"] == row["user_id"]
                and s["activity_id"] != row["activity_id"]
                and cutoff - timedelta(days=WINDOW_DAYS) <= s["started_at"] < cutoff
                and s["captured_at"] <= cutoff and s["ped"] is not None]
    eligible.sort(key=lambda s: (s["started_at"], s["activity_id"]))
    # One prospective snapshot per session. No carry-forward beyond seven days.
    values = [number(s["ped"]) for s in eligible]
    return {"latest": values[-1] if values else None,
            "rolling": mean(values) if len(values) >= MIN_ROLLING else None,
            # Strictly positive is a sign indicator, not a fatigue threshold.
            "persistent": float(all(v > 0 for v in values[-MIN_ROLLING:]))
            if len(values) >= MIN_ROLLING else None}


def replay_config(ablation):
    if ablation not in ABLATIONS:
        raise ValueError("unsupported_ped_ablation")
    config = baseline_prediction_config("0" * 64)
    if ablation == "response":
        config.update(response_enabled=False, response_max_weight=0.0)
    elif ablation == "feeling":
        config["feeling_enabled"] = False
    elif ablation == "physiology":
        config["historical_physiology_enabled"] = False
    return config


def fit_pair(pairs):
    """Matched-cohort OLS: y = a + b*readiness + c*PED, train only.

    Solve centered 2x2 normal equations; reject singular designs without ridge,
    imputation or hidden fallback. Baseline uses the identical train membership.
    """
    xs, zs, ys = zip(*pairs)
    xm, zm, ym = mean(xs), mean(zs), mean(ys)
    xx = binary64_sum((x-xm)**2 for x in xs)
    zz = binary64_sum((z-zm)**2 for z in zs)
    xz = binary64_sum((x-xm)*(z-zm) for x, z in zip(xs, zs))
    xy = binary64_sum((x-xm)*(y-ym) for x, y in zip(xs, ys))
    zy = binary64_sum((z-zm)*(y-ym) for z, y in zip(zs, ys))
    determinant = xx*zz-xz*xz
    if xx <= 1e-12 or determinant <= 1e-12 * max(1.0, xx*zz):
        raise ValueError("train_design_singular")
    b, c = (xy*zz-zy*xz)/determinant, (zy*xx-xy*xz)/determinant
    return {"baseline": [ym-xy/xx*xm, xy/xx, 0.0],
            "candidate": [ym-b*xm-c*zm, b, c]}


def predict(observations, state, dataset_hash, partition, candidate_id):
    artifacts = []
    for kind in ("baseline", "candidate"):
        a, b, c = [number(v) for v in state[kind]]
        predictions = [{"observation_id": row["observation_id"], "targets": {
            "next_day_recovery": {"value": max(1.0, min(5.0, a+b*number(row["x"])+c*number(row["z"])))}}}
                       for row in observations]
        artifacts.append({"prediction_schema_version": "prediction_artifact_v1",
                          "candidate_id": candidate_id+"-"+kind, "candidate_version": VERSION,
                          "dataset_hash": dataset_hash, "partition": partition,
                          "target_specs": [TARGET_SPEC], "predictions": predictions})
    return artifacts


def diagnostics(rows, baseline, candidate):
    by_id = [{p["observation_id"]: p["targets"]["next_day_recovery"]["value"]
              for p in artifact["predictions"]} for artifact in (baseline, candidate)]
    pairs = [(row, target_value(row), by_id[0][row["observation_id"]], by_id[1][row["observation_id"]])
             for row in rows if target_value(row) is not None and row["observation_id"] in by_id[0]]
    pairs.sort(key=lambda p: (p[0]["activity_local_date"], p[0]["observation_id"]))
    if not pairs:
        return {"paired_days": 0, "mae_delta_interval_95": None, "time_windows": []}
    deltas = [abs(c-y)-abs(b-y) for _, y, b, c in pairs]
    # Calendar-week block resampling keeps observations from one week together.
    blocks = {}
    from datetime import date
    for pair, delta in zip(pairs, deltas):
        day = date.fromisoformat(pair[0]["activity_local_date"])
        blocks.setdefault((day.toordinal()-day.weekday())//BLOCK_DAYS, []).append(delta)
    interval = None
    if len(blocks) >= 4:
        rng = random.Random(196)
        groups = list(blocks.values())
        estimates = sorted(mean([d for _ in groups for d in rng.choice(groups)]) for _ in range(BOOTSTRAPS))
        interval = [estimates[24], estimates[974]]
    windows = []
    for start in range(0, len(pairs), max(1, math.ceil(len(pairs)/3))):
        window = pairs[start:start+max(1, math.ceil(len(pairs)/3))]
        windows.append({"days": len(window), "start": window[0][0]["activity_local_date"],
                        "end": window[-1][0]["activity_local_date"],
                        "baseline_mae": mean(abs(b-y) for _, y, b, _ in window),
                        "candidate_mae": mean(abs(c-y) for _, y, _, c in window)})
    return {"paired_days": len(pairs), "mae_delta_interval_95": interval,
            "uncertainty_method": "calendar_week_block_bootstrap_seed196_1000",
            "time_windows": windows,
            # Point target calibration is mean signed error, never Brier/probability calibration.
            "baseline_mean_signed_error": mean(b-y for _, y, b, _ in pairs),
            "candidate_mean_signed_error": mean(c-y for _, y, _, c in pairs)}


def prepare_study(dataset, evidence, *, fit_as_of, partition="validation", test_access_granted=False):
    if partition not in ("validation", "test"):
        raise ValueError("ped_requires_held_out_partition")
    train, _, _ = validate_evaluation_dataset(dataset=dataset, partition="train")
    validation, _, _ = validate_evaluation_dataset(dataset=dataset, partition="validation")
    rows, _, _ = validate_evaluation_dataset(dataset=dataset, partition=partition,
                                            test_access_granted=test_access_granted)
    fit = timestamp(fit_as_of)
    if validation and fit >= min(timestamp(r["feature"]["cutoff_at"]) for r in validation):
        raise ValueError("fit_cutoff_not_before_validation")
    if any(timestamp(r["feature"]["cutoff_at"]) > fit for r in train):
        raise ValueError("train_feature_after_fit_cutoff")
    users = {r["user_id"] for r in train+validation+rows}
    if len(users) > 1:
        raise ValueError("cross_user_dataset_unsupported")
    snapshots = validate_snapshots(evidence)
    if users and any(s["user_id"] not in users for s in snapshots):
        raise ValueError("cross_user_ped_evidence")
    for row in train:
        if target_value(row) is not None and timestamp(row["outcome"]["targets"]["next_day_recovery"]["updated_at"]) > fit:
            raise ValueError("train_label_after_fit_cutoff")
    results, jobs = [], []
    for ablation in ABLATIONS:
        config = replay_config(ablation)
        for variant in VARIANTS:
            samples, missing = {}, {}
            for name, source in (("train", train), (partition, rows)):
                accepted, reasons = [], Counter()
                for row in source:
                    z = covariates(row, snapshots)[variant]
                    strata = "ped_present" if z is not None else "ped_missing"
                    reasons[strata] += 1
                    if target_value(row) is not None:
                        reasons[strata+"_target_available"] += 1
                    if z is None:
                        continue
                    try:
                        x = replay_readiness(row["feature"], config)/100
                    except ValueError:
                        reasons["baseline_replay_unavailable"] += 1
                        continue
                    # Inference observations exclude all labels and target timestamps.
                    accepted.append({"observation_id": row["observation_id"], "x": x, "z": z})
                samples[name], missing[name] = accepted, dict(reasons)
            targets = {r["observation_id"]: target_value(r) for r in train}
            fitted = [s for s in samples["train"] if targets[s["observation_id"]] is not None]
            result = {"variant": variant, "ablation": ablation,
                      "train_paired_days": len(fitted), "missingness_strata": missing,
                      "eligible_target_days": sum(target_value(r) is not None for r in rows),
                      "metrics": None, "uncertainty": None,
                      "recommendation": "insufficient_evidence", "reason": "insufficient_train_coverage"}
            if not validation:
                result["reason"] = "validation_boundary_unavailable"
            elif len(fitted) >= MIN_TRAIN_DAYS:
                try:
                    state = fit_pair([(s["x"], s["z"], targets[s["observation_id"]]) for s in fitted])
                except ValueError:
                    result["reason"] = "train_design_singular"
                else:
                    result["reason"] = None
                    jobs.append({"result_index": len(results), "state": state,
                                 "observations": samples[partition]})
            results.append(result)
    report = {"study_version": VERSION, "dataset_hash": dataset["manifest"]["dataset_hash"],
              "evidence_hash": canonical_hash(evidence), "fit_as_of": fit.isoformat(),
              "partition": partition, "day_counts": {"train": len(train), partition: len(rows)},
              "recommendation": "insufficient_evidence", "results": results,
              "limits": ["prospective_PED_capture_required", "no_causal_interpretation",
                         "aggregate_readiness_adjustment_not_individual_HRV_RHR_sleep_control",
                         "no_production_promotion", "self_report_target_not_independent_physiology"]}
    return report, jobs


def finish_comparison(report, job, dataset, artifacts, *, test_access_granted=False):
    index = job["result_index"]
    baseline, candidate = artifacts
    evaluation = evaluate_research_candidate(dataset=dataset, partition=report["partition"],
        baseline_artifact=baseline, candidate_artifact=candidate, test_access_granted=test_access_granted)
    result = report["results"][index]
    result["metrics"] = evaluation
    result["uncertainty"] = diagnostics(dataset["partitions"][report["partition"]], baseline, candidate)
    paired = result["uncertainty"]["paired_days"]
    coverage = paired/result["eligible_target_days"] if result["eligible_target_days"] else 0.0
    result["paired_coverage"] = coverage
    result["reason"] = "insufficient_paired_coverage"
    if paired >= MIN_PAIRED_DAYS and coverage >= MIN_PAIRED_COVERAGE:
        result["reason"] = "separate_review_required"
        result["recommendation"] = "refine"
    # No automatic adopt/reject threshold from exploratory multiple comparisons.
    if any(r["recommendation"] == "refine" for r in report["results"]):
        report["recommendation"] = "refine"
    return evaluation
