"""Preparation readiness is aggregate evidence, never real acceptance coverage."""

from copy import deepcopy
import json
import subprocess
import sys
from backend.services.recovery_data_readiness import recovery_data_readiness
from test_recovery_prediction import dataset_fixture, rehash, FIT_TIME, prepared
from backend.services.temporal_dataset_v2 import build_day_dataset


def test_ready_deterministic_private_and_matches_preparation():
    dataset, state, _, artifact = prepared()
    original = deepcopy(dataset)
    report = recovery_data_readiness(dataset, fit_as_of=FIT_TIME)
    assert report == recovery_data_readiness(dataset, fit_as_of=FIT_TIME)
    assert dataset == original
    assert report["status"] == "ready_for_preparation"
    assert report["train"]["eligible_days"] == state["sample_count"] == 30
    assert report["validation"]["potential_baseline_pair_days"] == len(artifact["predictions"]) == 20
    assert report["actual_paired_coverage"] is None
    encoded = json.dumps(report)
    for secret in ("fixture-user", "observation_id", "score", "alpha", "beta"):
        assert secret not in encoded


def test_legacy_only_snapshots_and_first_activity_exclusion():
    _, records, snapshots, split = dataset_fixture()
    for snapshot in snapshots:
        snapshot["feature_vector_version"] = "daily_feature_vector_v1"
    data = build_day_dataset(records=records, feature_snapshots=snapshots,
                            split=split, timezone_name="Europe/Moscow")
    report = recovery_data_readiness(data, fit_as_of=FIT_TIME)
    assert report["status"] == "insufficient_data"
    assert report["train"]["canonical_days"] == 30
    assert report["train"]["eligible_days"] == 0
    assert report["export_exclusions_unverified"]["train"]["response_baseline_context_not_snapshotted"] == 30
    _, records, snapshots, split = dataset_fixture()
    earlier = deepcopy(records[0])
    earlier.update(activity_id=1000, decision=None)
    earlier["activity_start_at"] = records[0]["activity_start_at"].replace(hour=7)
    data = build_day_dataset(records=[earlier] + records, feature_snapshots=snapshots,
                            split=split, timezone_name="Europe/Moscow")
    report = recovery_data_readiness(data, fit_as_of=FIT_TIME)
    assert report["train"]["eligible_days"] == 29
    assert report["export_exclusions_unverified"]["train"]["eligible_day_start_decision_missing"] == 1


def test_missing_target_replay_and_coverage_denominator():
    dataset = dataset_fixture(validation_days=30)[0]
    for row in dataset["partitions"]["validation"][:8]:
        row["feature"]["values"]["response_replay_context"]["availability"] = "unsupported"
        row["feature"]["values"]["response_replay_context"]["reason_codes"] = ["response_as_of_state_unprovable"]
    rehash(dataset)
    report = recovery_data_readiness(dataset, fit_as_of=FIT_TIME)
    assert report["validation"]["potential_baseline_pair_days"] == 22
    assert report["validation"]["compatible_target_days"] == 30
    assert report["status"] == "insufficient_data"
    assert report["validation"]["potential_baseline_pair_fraction"] == 22/30
    dataset = dataset_fixture()[0]
    dataset["partitions"]["train"][0]["outcome"]["targets"]["next_day_recovery"]["status"] = "missing"
    rehash(dataset)
    report = recovery_data_readiness(dataset, fit_as_of=FIT_TIME)
    assert report["train"]["missing_or_incompatible_target_days"] == 1
    assert report["train"]["eligible_days"] == 29


def test_late_receipt_and_fit_embargo():
    dataset = dataset_fixture()[0]
    dataset["partitions"]["train"][0]["outcome"]["targets"]["next_day_recovery"]["updated_at"] = "2026-02-02T12:00:00+00:00"
    rehash(dataset)
    report = recovery_data_readiness(dataset, fit_as_of=FIT_TIME)
    assert report["train"]["labels_after_fit_cutoff"] == 1
    assert "train_label_after_fit_cutoff" in report["reasons"]
    report = recovery_data_readiness(dataset, fit_as_of="2026-02-02T12:00:00+00:00")
    assert "fit_cutoff_not_before_validation" in report["reasons"]


def test_variance_gate():
    dataset = dataset_fixture()[0]
    for row in dataset["partitions"]["train"]:
        row["feature"]["values"]["features"]["load.freshness"]["value"] = 0
    rehash(dataset)
    report = recovery_data_readiness(dataset, fit_as_of=FIT_TIME)
    assert report["train"]["eligible_days"] == 30
    assert not report["train"]["readiness_variance_sufficient"]
    assert "train_readiness_variance_insufficient" in report["reasons"]


def test_invalid_hash_temporal_provenance_and_test_denial():
    dataset = dataset_fixture()[0]
    dataset["partitions"]["train"][0]["row_hash"] = "wrong"
    assert recovery_data_readiness(dataset, fit_as_of=FIT_TIME)["status"] == "invalid_dataset"
    dataset = dataset_fixture()[0]
    dataset["partitions"]["validation"][0]["feature"]["captured_at"] = "2099-01-01T00:00:00Z"
    rehash(dataset)
    assert recovery_data_readiness(dataset, fit_as_of=FIT_TIME)["status"] == "invalid_dataset"
    dataset["partitions"]["test"] = [{"private": "do not inspect"}]
    assert recovery_data_readiness(dataset, fit_as_of=FIT_TIME)["reasons"] == ["test_export_not_allowed"]


def test_unbound_export_metadata_cannot_print_pii():
    dataset = dataset_fixture()[0]
    dataset["manifest"]["excluded_observations"] = [
        {"partition": "test", "reason": "private"},
        {"partition": "train", "reason": "private"},
    ]
    assert "private" not in json.dumps(recovery_data_readiness(dataset, fit_as_of=FIT_TIME))


def test_cli_read_only_and_sanitized_failure(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps(dataset_fixture()[0]))
    command = [sys.executable, "-m", "scripts.report_recovery_data_readiness",
               "--dataset", str(dataset), "--fit-as-of", FIT_TIME]
    before = dataset.read_bytes()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ready_for_preparation"
    assert dataset.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dataset.json"]
    dataset.write_text('{"private-personal-data": invalid}')
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    assert "private-personal-data" not in result.stdout + result.stderr


def test_malformed_envelopes_and_unbound_metadata_are_sanitized():
    for data in (None, [], {}, {"partitions": {}, "manifest": None}):
        assert recovery_data_readiness(data, fit_as_of=FIT_TIME)["status"] == "invalid_dataset"
    dataset = dataset_fixture()[0]
    dataset["manifest"]["split"]["private"] = "personal-data"
    dataset["manifest"]["excluded_observations"] = [{"partition": [], "reason": {}}]
    rehash(dataset)
    report = recovery_data_readiness(dataset, fit_as_of=FIT_TIME)
    assert report["status"] == "ready_for_preparation"
    assert "personal-data" not in json.dumps(report)
