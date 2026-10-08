"""Real deterministic model tests; synthetic evidence is not production coverage."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import pytest

from backend.services.recovery_prediction import (
    replay_readiness, fit_recovery_state, prediction_artifact, canonical_hash, timestamp,
)
from backend.services.recovery_prediction_config import baseline_prediction_config
from backend.services.research_parameter_space import candidate_config_hash, baseline_candidate_config
from backend.services.readiness_composition import compose_readiness
from backend.services.temporal_dataset import TemporalSplit
from backend.services.temporal_dataset_v2 import build_day_dataset
from backend.services import research_evaluator_v2 as evaluator
from backend.services import research_runner as runner
from backend.services.research_container import DockerExecutor
from scripts.research_worker import process_request

UTC = timezone.utc
START = date(2026, 1, 1)
FIT_TIME = "2026-01-31T22:00:00+00:00"


def evidence(index, *, freshness=None, feeling=4, response_context=None):
    day = START + timedelta(days=index)
    cutoff = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=6)
    def field(value):
        return ({"availability": "unavailable", "value": None, "reason_codes": ["missing"]}
                if value is None else {"availability": "available", "value": value,
                                      "reason_codes": [], "available_at": cutoff.isoformat()})
    replay = {"context_version": "response_replay_context_v1", "availability": "unavailable",
              "context": None, "reason_codes": ["no_eligible_response_as_of_cutoff"]}
    if response_context:
        replay.update(availability="available", context=response_context, reason_codes=[],
                      date_basis="stored_activity_date",
                      activity_start_at=(cutoff-timedelta(days=1)).isoformat(),
                      source_available_at=(cutoff-timedelta(hours=12)).isoformat(),
                      computed_at=(cutoff-timedelta(hours=11)).isoformat())
    vector = {
        "feature_vector_version": "daily_feature_vector_v2", "user_id": "fixture-user",
        "local_date": day.isoformat(), "cutoff_at": cutoff.isoformat(), "timezone": "Europe/Moscow",
        "features": {"load.freshness": field((index % 5)*15-30 if freshness is None else freshness),
                     "feeling.next_day_recovery_score": field(feeling),
                     "physiology.historical.recovery_score": field(None)},
        "response_replay_context": replay,
    }
    return {"snapshot_id": index+1, "feature_vector_version": "daily_feature_vector_v2",
            "values": vector, "cutoff_at": cutoff.isoformat(), "captured_at": cutoff.isoformat()}


def dataset_fixture(*, train_days=30, validation_days=20):
    records, snapshots = [], []
    for index in range(train_days+validation_days):
        # D+1 labels need a receipt-time embargo before validation inference.
        day_index = index + (1 if index >= train_days else 0)
        feature = evidence(day_index)
        day = START + timedelta(days=day_index)
        cutoff = timestamp(feature["cutoff_at"])
        records.append({
            "user_id": "fixture-user", "activity_id": index+1, "activity_local_date": day,
            "activity_start_at": cutoff+timedelta(hours=2),
            "decision": {"status": "available", "source_id": index+1,
                         "captured_at": cutoff.isoformat(), "readiness_computed_at": cutoff.isoformat()},
            "outcome": {"contract_version": "workout_outcome_v1", "targets": {
                "next_day_recovery": {"unit": "training_day", "status": "available",
                                     "score": index%5+1, "scale": "1-5",
                                     "target_local_date": (day+timedelta(days=1)).isoformat(),
                                     "updated_at": (cutoff+timedelta(days=1)).isoformat()}}},
        })
        snapshots.append({
            "id": index+1, "user_id": "fixture-user", "local_date": day,
            "feature_vector_version": "daily_feature_vector_v2",
            "cutoff_at": cutoff, "captured_at": cutoff, "feature_json": feature["values"],
        })
    split = TemporalSplit(START, START+timedelta(days=train_days-1),
                          START+timedelta(days=train_days+validation_days),
                          START+timedelta(days=train_days+validation_days+2))
    return build_day_dataset(records=records, feature_snapshots=snapshots,
                             split=split, timezone_name="Europe/Moscow"), records, snapshots, split


def rehash(dataset):
    rows = [r for rows in dataset["partitions"].values() for r in rows]
    for row in rows:
        row["row_hash"] = canonical_hash({k:v for k,v in row.items() if k != "row_hash"})
    dataset["manifest"]["row_hashes"] = [r["row_hash"] for r in rows]
    dataset["manifest"]["dataset_hash"] = canonical_hash({k:dataset["manifest"][k] for k in evaluator.MANIFEST_KEYS})


def prepared():
    dataset = dataset_fixture()[0]
    state = fit_recovery_state(dataset, fit_as_of=FIT_TIME)
    config = baseline_prediction_config(canonical_hash(state))
    artifact, _ = prediction_artifact(observations=dataset["partitions"]["validation"],
                                      config=config, state=state, dataset_hash=dataset["manifest"]["dataset_hash"],
                                      partition="validation")
    return dataset, state, config, artifact


@pytest.mark.parametrize("feeling", [None, 1, 3, 5])
@pytest.mark.parametrize("age", [0, 1, 2, 6, 7])
def test_exact_baseline_formula_and_response_rounding(feeling, age):
    feature = evidence(10, freshness=13.37, feeling=feeling)
    context = {"version": "v2_rpe_1_10",
               "activity_date": (START+timedelta(days=10-age)).isoformat(),
               "baseline": {"metrics": {
                   "normalized_power_to_hr": {"current": 2.1, "median": 2, "deviation_pct": 5.0},
                   "aerobic_decoupling_pct": {"current": 4, "median": 2, "deviation_pct": 100.0},
                   "session_rpe_load_per_tss": {"current": 3.2, "median": 3, "deviation_pct": 6.667},
               }}}
    # timestamp provenance is independent of activity_date recency for this fixture.
    feature = evidence(10, freshness=13.37, feeling=feeling, response_context=context)
    config = baseline_prediction_config("0"*64)
    actual = replay_readiness(feature, config)
    expected = compose_readiness(load_context={}, freshness=13.37, feeling_score=feeling,
                                 physiology_score=None, physiology_explanation=None,
                                 response_context=context, target_date=feature["values"]["local_date"])
    assert actual == expected["readiness_score"]


def test_exact_no_response_baseline_and_parameter_effect():
    feature = evidence(10, freshness=-20, feeling=5)
    config = baseline_prediction_config("0"*64)
    baseline = replay_readiness(feature, config)
    candidate = {**config, "freshness_weight": 0.8, "recovery_evidence_weight": 0.2}
    assert replay_readiness(feature, candidate) < baseline
    missing = deepcopy(feature)
    missing["values"]["features"]["feeling.next_day_recovery_score"] = {
        "availability": "unavailable", "value": None, "reason_codes": ["missing"]}
    assert replay_readiness(missing, config) == replay_readiness(missing, candidate) == 30


def test_thresholds_partial_unknown_and_legacy_configs_rejected():
    config = baseline_prediction_config("0"*64)
    for invalid in ({**config, "recovery_threshold": 35}, {**config, "code": "eval()"},
                    {k:v for k,v in config.items() if k != "learned_state_hash"}):
        with pytest.raises(ValueError):
            candidate_config_hash(invalid)
    with pytest.raises(ValueError, match="snapshotted"):
        replay_readiness({"feature_vector_version":"daily_feature_vector_v1"}, config)


@pytest.mark.parametrize("mutation, reason", [
    ("feature_time", "post_cutoff_feature"), ("response_time", "post_cutoff_response"),
    ("capability", "snapshotted"), ("nan", "invalid_numeric"),
])
def test_missing_unsupported_and_temporal_leakage(mutation, reason):
    config = baseline_prediction_config("0"*64)
    feature = evidence(10)
    if mutation == "feature_time":
        feature["values"]["features"]["load.freshness"]["available_at"] = "2026-02-01T00:00:00+00:00"
    elif mutation == "capability":
        feature["values"].pop("response_replay_context")
    elif mutation == "nan":
        feature["values"]["features"]["load.freshness"]["value"] = float("nan")
    else:
        feature["values"]["response_replay_context"].update(
            availability="available", context={"version":"v2_rpe_1_10"},
            date_basis="stored_activity_date", activity_start_at=feature["cutoff_at"],
            source_available_at=feature["cutoff_at"], computed_at="2026-02-01T00:00:00+00:00")
    with pytest.raises(ValueError, match=reason):
        replay_readiness(feature, config)


def test_fit_reads_only_train_labels_and_is_repeatable():
    dataset, state, config, baseline = prepared()
    poisoned = deepcopy(dataset)
    for row in poisoned["partitions"]["validation"]:
        row["outcome"] = {"do_not_read": "validation labels"}
    assert fit_recovery_state(poisoned, fit_as_of=FIT_TIME) == state
    assert fit_recovery_state(dataset, fit_as_of=FIT_TIME) == state
    artifact, _ = prediction_artifact(observations=dataset["partitions"]["validation"], config=config,
                                      state=state, dataset_hash=dataset["manifest"]["dataset_hash"],
                                      partition="validation")
    assert artifact == baseline
    assert all(1 <= r["targets"]["next_day_recovery"]["value"] <= 5 for r in artifact["predictions"])


def test_fit_rejects_post_cutoff_labels_low_coverage_and_zero_variance():
    dataset = dataset_fixture(train_days=29)[0]
    with pytest.raises(ValueError, match="insufficient_train"):
        fit_recovery_state(dataset, fit_as_of="2026-01-30T22:00:00+00:00")
    dataset = dataset_fixture()[0]
    dataset["partitions"]["train"][0]["outcome"]["targets"]["next_day_recovery"]["updated_at"] = "2026-02-03T00:00:00+00:00"
    rehash(dataset)
    with pytest.raises(ValueError, match="train_label_after"):
        fit_recovery_state(dataset, fit_as_of=FIT_TIME)
    dataset = dataset_fixture()[0]
    for row in dataset["partitions"]["train"]:
        row["feature"]["values"]["features"]["load.freshness"]["value"] = 0
    rehash(dataset)
    with pytest.raises(ValueError, match="variance"):
        fit_recovery_state(dataset, fit_as_of=FIT_TIME)


def test_day_owner_is_first_canonical_activity_even_if_ineligible():
    dataset, records, snapshots, split = dataset_fixture()
    first = records[0]
    later = deepcopy(first)
    later["activity_id"] = 999
    later["activity_start_at"] += timedelta(hours=2)
    original = build_day_dataset(records=list(reversed(records+[later])), feature_snapshots=snapshots,
                                 split=split, timezone_name="Europe/Moscow")
    assert original == dataset
    first["decision"] = None
    excluded = build_day_dataset(records=records+[later], feature_snapshots=snapshots,
                                 split=split, timezone_name="Europe/Moscow")
    assert len(excluded["partitions"]["train"]) == 29
    assert excluded["manifest"]["canonical_day_counts"]["train"] == 30


def test_corrupt_hash_bad_partition_and_test_access_fail():
    dataset = dataset_fixture()[0]
    changed = deepcopy(dataset)
    changed["partitions"]["validation"][0]["feature"]["values"]["features"]["load.freshness"]["value"] = 100
    with pytest.raises(ValueError, match="hash"):
        evaluator.validate_evaluation_dataset(dataset=changed, partition="validation")
    with pytest.raises(PermissionError):
        evaluator.validate_evaluation_dataset(dataset=dataset, partition="test")
    changed = deepcopy(dataset)
    changed["partitions"]["validation"][0]["activity_local_date"] = "2026-01-01"
    rehash(changed)
    with pytest.raises(ValueError, match="boundary"):
        evaluator.validate_evaluation_dataset(dataset=changed, partition="validation")


def test_frozen_evaluator_and_model_parameter_effect():
    dataset, state, config, baseline = prepared()
    config.update(freshness_weight=0.8, recovery_evidence_weight=0.2)
    candidate, _ = prediction_artifact(observations=dataset["partitions"]["validation"], config=config,
                                      state=state, dataset_hash=dataset["manifest"]["dataset_hash"],
                                      partition="validation")
    assert candidate["predictions"] != baseline["predictions"]
    result = evaluator.evaluate_research_candidate(dataset=dataset, partition="validation",
                                                   baseline_artifact=baseline, candidate_artifact=candidate)
    assert result["comparison"]["targets"][0]["paired_count"] == 20
    assert result["evaluator_version"] == evaluator.EVALUATOR_VERSION
    assert result["dataset"]["dataset_version"] == "temporal_dataset_v2"


def test_real_worker_runner_audit_path_and_repeatability(tmp_path, monkeypatch):
    dataset, state, config, baseline = prepared()
    calls, requests = [], []
    monkeypatch.setattr(runner, "create_research_experiment", lambda **kw: calls.append(kw))
    def finish(**kw):
        calls.append(kw)
        return {"status":kw["status"]}
    monkeypatch.setattr(runner, "finish_research_experiment", finish)
    def execute(self, request, directory):
        requests.append(deepcopy(request))
        return {"metadata":{"failure_reason":None,"cleanup_succeeded":True},
                "response":process_request(request)}
    monkeypatch.setattr(DockerExecutor, "execute", execute)
    args = dict(dataset=dataset, config=config, learned_state=state, baseline=baseline,
                experiment_id="real-model", hypothesis="Deterministic model fixture",
                image="sha256:"+"a"*64, output_root=tmp_path/"private", connection_factory=lambda:None)
    assert runner.run_research_experiment(**args)["status"] == "candidate"
    assert calls[-1]["execution_metadata"]["coverage"]["paired_days"] == 20
    candidate_input = json.dumps(requests[0])
    assert '"outcome"' not in candidate_input and '"decision"' not in candidate_input
    assert "updated_at" not in candidate_input  # No target availability timestamp enters inference.
    evaluation_hash = calls[-1]["metrics"]["evaluation_hash"]
    args["experiment_id"] = "repeat"
    assert runner.run_research_experiment(**args)["status"] == "candidate"
    assert calls[-1]["metrics"]["evaluation_hash"] == evaluation_hash
    with pytest.raises(FileExistsError):
        runner.run_research_experiment(**args)
    # A forged baseline cannot create an audit record.
    args["baseline"] = deepcopy(baseline)
    args["baseline"]["predictions"][0]["targets"]["next_day_recovery"]["value"] = 5
    with pytest.raises(ValueError, match="baseline_prediction_identity"):
        runner.run_research_experiment(**args)


def test_forged_state_coefficients_cannot_pass_train_verification(tmp_path, monkeypatch):
    dataset, state, config, _ = prepared()
    state["beta"] += 1
    config = baseline_prediction_config(canonical_hash(state))
    artifact, _ = prediction_artifact(observations=dataset["partitions"]["validation"], config=config,
                                      state=state, dataset_hash=dataset["manifest"]["dataset_hash"],
                                      partition="validation")
    monkeypatch.setattr(runner, "create_research_experiment", lambda **kw: pytest.fail("audit started"))
    with pytest.raises(ValueError, match="train_membership"):
        runner.run_research_experiment(
            dataset=dataset, config=config, learned_state=state, baseline=artifact, experiment_id="forged",
            hypothesis="Forged fit", image="sha256:"+"a"*64, output_root=tmp_path/"private",
            connection_factory=lambda: None)


@pytest.mark.parametrize("validation_days, missing_days", [(19, 0), (30, 8)])
def test_insufficient_paired_coverage_is_a_failed_audit_run(tmp_path, monkeypatch, validation_days, missing_days):
    dataset = dataset_fixture(validation_days=validation_days)[0]
    for row in dataset["partitions"]["validation"][:missing_days]:
        for name in row["feature"]["values"]["features"]:
            row["feature"]["values"]["features"][name] = {
                "availability":"unavailable","value":None,"reason_codes":["missing"]}
    rehash(dataset)
    state = fit_recovery_state(dataset, fit_as_of=FIT_TIME)
    config = baseline_prediction_config(canonical_hash(state))
    artifact, _ = prediction_artifact(observations=dataset["partitions"]["validation"], config=config,
                                      state=state, dataset_hash=dataset["manifest"]["dataset_hash"],
                                      partition="validation")
    audit = []
    monkeypatch.setattr(runner, "create_research_experiment", lambda **kw: None)
    def finish(**kw):
        audit.append(kw)
        return {"status": kw["status"]}
    monkeypatch.setattr(runner, "finish_research_experiment", finish)
    monkeypatch.setattr(DockerExecutor, "execute", lambda self, request, directory:
                        {"metadata":{"failure_reason":None,"cleanup_succeeded":True},
                         "response":process_request(request)})
    result = runner.run_research_experiment(
        dataset=dataset, config=config, learned_state=state, baseline=artifact, experiment_id="low-coverage",
        hypothesis="Insufficient data", image="sha256:"+"a"*64, output_root=tmp_path/"private",
        connection_factory=lambda: None)
    assert result["failure_reason"] == "insufficient_paired_coverage"
    assert result["status"] == "failed" and audit[-1]["metrics"] is None
    assert audit[-1]["execution_metadata"]["coverage"]["paired_days"] == validation_days-missing_days
    if missing_days:
        assert audit[-1]["execution_metadata"]["missing_prediction_reasons"] == {"no_scored_readiness_signal":missing_days}


def test_no_scored_family_and_disabled_response_do_not_impute():
    feature = evidence(0)
    for name in feature["values"]["features"]:
        feature["values"]["features"][name] = {"value":None,"availability":"unavailable","reason_codes":["missing"]}
    with pytest.raises(ValueError, match="no_scored"):
        replay_readiness(feature, baseline_prediction_config("0"*64))
    feature["values"].pop("response_replay_context")
    config = baseline_prediction_config("0"*64)
    config.update(response_enabled=False, response_max_weight=0.0)
    with pytest.raises(ValueError, match="snapshotted"):
        replay_readiness(feature, config)


@pytest.mark.parametrize("has_response", [False, True, "late"])
def test_v2_builder_copies_response_baseline_in_same_source_transaction(monkeypatch, has_response):
    from backend.services import daily_feature_vector as builder
    cutoff = datetime(2026, 1, 2, 6, tzinfo=UTC)
    baseline = {"metrics":{"normalized_power_to_hr":{"current":2.5,"median":2.0,"deviation_pct":25}}}
    results = [
        [(55, 40, 20, 30, 25, 15, cutoff-timedelta(minutes=1))], [],
        [(4, cutoff-timedelta(minutes=2), cutoff-timedelta(minutes=1))], [], [],
        [(1, date(2026,1,1), "v2_rpe_1_10", "endurance", baseline, {}, {},
          cutoff-timedelta(days=1), cutoff-timedelta(hours=12),
          cutoff+timedelta(seconds=1) if has_response == "late" else cutoff-timedelta(hours=11))] if has_response else [],
    ]
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self, query, params=None):
            queries.append((query,params))
            if query.strip().startswith("select"):
                self.rows = results.pop(0)
        def fetchone(self): return self.rows[0] if self.rows else None
        def fetchall(self): return self.rows
    class Connection:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def cursor(self): return Cursor()
    queries, connections = [], []
    def connect():
        connections.append(1)
        return Connection()
    monkeypatch.setattr(builder,"get_conn",connect)
    vector = builder.build_daily_feature_vector(
        user_id="fixture-user", local_date=date(2026,1,2), cutoff_at=cutoff,
        timezone_name="Europe/Moscow", feature_vector_version="daily_feature_vector_v2")
    assert len(connections) == 1
    assert "repeatable read, read only" in queries[0][0]
    expected = "unsupported" if has_response == "late" else "available" if has_response else "unavailable"
    assert vector["response_replay_context"]["availability"] == expected
    if has_response == "late":
        assert vector["response_replay_context"]["reason_codes"] == ["response_as_of_state_unprovable"]
    elif has_response:
        assert vector["response_replay_context"]["context"]["baseline"] == baseline
        assert "arm.computed_at" in queries[-1][0]
        persisted = json.dumps(vector)
        baseline["metrics"]["normalized_power_to_hr"]["median"] = 99
        # JSON serialization is the immutable boundary, not a live row reference.
        assert json.loads(persisted)["response_replay_context"]["context"]["baseline"]["metrics"]["normalized_power_to_hr"]["median"] == 2.0


def test_preparation_cli_freezes_private_files_and_never_overwrites(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    dataset = dataset_fixture()[0]
    source = tmp_path/"dataset.json"
    source.write_text(json.dumps(dataset))
    output = tmp_path/"prepared"
    command = [sys.executable,"-m","scripts.prepare_recovery_prediction","--dataset",str(source),
               "--fit-as-of",FIT_TIME,"--output-root",str(output)]
    env = {**os.environ,"PYTHONPATH":str(Path(__file__).resolve().parents[1])}
    prepared_run = subprocess.run(command,env=env,capture_output=True,text=True,check=True,timeout=10)
    assert json.loads(prepared_run.stdout)["status"] == "prepared"
    assert output.stat().st_mode & 0o777 == 0o700
    for path in output.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    first = (output/"learned-state.json").read_bytes()
    retry = subprocess.run(command,env=env,capture_output=True,text=True,timeout=10)
    assert retry.returncode != 0
    assert (output/"learned-state.json").read_bytes() == first


def test_dataset_keeps_feedback_edits_and_timezone_attribution_explicit():
    dataset, records, snapshots, split = dataset_fixture()
    frozen_hash = dataset["manifest"]["dataset_hash"]
    records[0]["outcome"]["targets"]["next_day_recovery"]["score"] = 5
    edited = build_day_dataset(records=records,feature_snapshots=snapshots,split=split,
                               timezone_name="Europe/Moscow")
    assert edited["manifest"]["dataset_hash"] != frozen_hash
    assert dataset["partitions"]["train"][0]["outcome"]["targets"]["next_day_recovery"]["score"] == 1
    # UTC Jan-01 22:00 is local Jan-02; claiming Jan-01 is incompatible.
    bad = deepcopy(dataset)
    bad["partitions"]["train"][0]["activity_start_at"] = "2026-01-01T22:00:00+00:00"
    rehash(bad)
    with pytest.raises(ValueError, match="activity_local_date"):
        evaluator.validate_evaluation_dataset(dataset=bad,partition="train")
    # Unrecognized outcome definitions cannot become v1 by export.
    records[0]["outcome"]["contract_version"] = "future_unknown"
    with pytest.raises(ValueError,match="unsupported_outcome"):
        build_day_dataset(records=records,feature_snapshots=snapshots,split=split,
                          timezone_name="Europe/Moscow")
