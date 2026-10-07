"""Supervisor protocol tests use synthetic artifacts, never a production predictor."""

from copy import deepcopy
import json

import pytest

from backend.services import research_runner as runner
from backend.services.research_container import ResourceLimits, DockerExecutor, validate_image
from backend.services.research_parameter_space import baseline_candidate_config, candidate_config_hash
from backend.services.research_evaluator import evaluate_research_candidate
from scripts.research_worker import process_request
from test_research_evaluator import _dataset, _artifact

IMAGE = "sha256:" + "a" * 64


def inputs(tmp_path):
    dataset = _dataset()
    for row in dataset["partitions"]["validation"]:
        row["feature"] = {"feature_vector_version": "daily_feature_vector_v1",
                          "values": {"features": {"load.freshness": {"value": 3, "availability": "available"}}}}
        # Rehash synthetic fixtures after adding feature payloads.
        from test_research_evaluator import _canonical_hash
        row["row_hash"] = _canonical_hash({k: v for k, v in row.items() if k != "row_hash"})
    manifest = dataset["manifest"]
    manifest["row_hashes"] = [row["row_hash"] for row in dataset["partitions"]["validation"]]
    manifest["dataset_hash"] = _canonical_hash({k: v for k, v in manifest.items() if k != "dataset_hash"})
    baseline = _artifact("baseline", rpe={"obs-1": {"value": 5}, "obs-2": {"value": 7}},
                         binary={"obs-1": {"probability": 0.8}, "obs-2": {"probability": 0.4}})
    baseline["dataset_hash"] = manifest["dataset_hash"]
    root = tmp_path / "private"
    return dict(config=baseline_candidate_config(), dataset=dataset, baseline=baseline,
                experiment_id="run-001", hypothesis="Protocol verification", image=IMAGE,
                output_root=root, connection_factory=lambda: None)


@pytest.fixture
def audit(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "create_research_experiment", lambda **kw: calls.append(("create", kw)))
    def finish(**kw):
        calls.append(("finish", kw))
        return {"status": kw["status"]}
    monkeypatch.setattr(runner, "finish_research_experiment", finish)
    return calls


def stage(response, reason=None):
    return {"metadata": {"failure_reason": reason, "cleanup_succeeded": True, "exit_code": 0,
                         "duration_ms": 10, "oom_killed": False, "timed_out": False},
            "response": response}


def install_success(monkeypatch, arguments, requests):
    def execute(self, request, directory):
        requests.append(request)
        if request["operation"] == "candidate":
            artifact = deepcopy(arguments["baseline"])
            artifact.update(candidate_id=candidate_config_hash(arguments["config"]),
                            candidate_version=arguments["config"]["candidate_model_version"])
            return stage({"protocol_version": runner.PROTOCOL_VERSION, "status": "ok",
                          "candidate_config_hash": candidate_config_hash(arguments["config"]), "result": artifact})
        return stage(process_request(request))
    monkeypatch.setattr(DockerExecutor, "execute", execute)


def test_success_protocol_with_synthetic_predictions(tmp_path, monkeypatch, audit):
    arguments, requests = inputs(tmp_path), []
    install_success(monkeypatch, arguments, requests)
    result = runner.run_research_experiment(**arguments)
    assert result["status"] == "candidate"
    assert [c[0] for c in audit] == ["create", "finish"]
    assert "outcome" not in json.dumps(requests[0])
    assert "decision" not in json.dumps(requests[0])
    assert "outcome" in json.dumps(requests[1])
    assert set(requests[1]["dataset"]["partitions"]) == {"validation"}
    assert audit[-1][1]["metrics"]["metric_specification_hash"]
    receipt = json.loads((arguments["output_root"] / "run-001/receipt.json").read_text())
    assert receipt["persisted"] is True
    assert len(receipt["execution_metadata"]["stages"]) == 2


@pytest.mark.parametrize("reason", ["wall_clock_timeout", "container_oom_killed", "candidate_process_failed", "container_output_limit_exceeded"])
def test_execution_failures_persist_without_metrics(tmp_path, monkeypatch, audit, reason):
    monkeypatch.setattr(DockerExecutor, "execute", lambda *a: stage(None, reason))
    result = runner.run_research_experiment(**inputs(tmp_path))
    assert result["status"] == "failed"
    assert result["failure_reason"] == reason
    assert audit[-1][1]["metrics"] is None


@pytest.mark.parametrize("response_enabled, reason", [
    (True, "response_baseline_context_not_snapshotted"),
    (False, "outcome_prediction_contract_not_implemented"),
])
def test_builtin_worker_explicitly_rejects_unsupported_model(tmp_path, monkeypatch, audit, response_enabled, reason):
    arguments = inputs(tmp_path)
    if not response_enabled:
        arguments["config"].update(response_enabled=False, response_max_weight=0.0)
    monkeypatch.setattr(DockerExecutor, "execute", lambda self, request, directory: stage(process_request(request), "candidate_process_failed"))
    result = runner.run_research_experiment(**arguments)
    assert result["failure_reason"] == reason
    assert audit[-1][1]["status"] == "failed"


def test_invalid_config_and_corrupt_dataset_never_start_experiment(tmp_path, audit):
    arguments = inputs(tmp_path)
    arguments["config"]["freshness_weight"] = 9
    with pytest.raises(ValueError):
        runner.run_research_experiment(**arguments)
    arguments = inputs(tmp_path)
    arguments["dataset"]["partitions"]["validation"][0]["outcome"] = {}
    with pytest.raises(ValueError, match="hash"):
        runner.run_research_experiment(**arguments)
    assert audit == []


def test_test_access_requires_explicit_grant(tmp_path, audit):
    arguments = inputs(tmp_path)
    arguments["partition"] = "test"
    with pytest.raises(PermissionError):
        runner.run_research_experiment(**arguments)
    assert audit == []


def test_repeated_execution_is_reproducible_and_duplicate_id_fails(tmp_path, monkeypatch, audit):
    arguments, requests = inputs(tmp_path), []
    install_success(monkeypatch, arguments, requests)
    runner.run_research_experiment(**arguments)
    first_hash = audit[-1][1]["metrics"]["evaluation_hash"]
    with pytest.raises(FileExistsError):
        runner.run_research_experiment(**arguments)
    arguments["experiment_id"] = "run-002"
    runner.run_research_experiment(**arguments)
    assert audit[-1][1]["metrics"]["evaluation_hash"] == first_hash


def test_failed_persistence_leaves_private_receipt(tmp_path, monkeypatch, audit):
    arguments, requests = inputs(tmp_path), []
    install_success(monkeypatch, arguments, requests)
    def fail(**kw):
        raise RuntimeError("private database credential")
    monkeypatch.setattr(runner, "finish_research_experiment", fail)
    with pytest.raises(RuntimeError, match="audit_persistence_failed") as error:
        runner.run_research_experiment(**arguments)
    assert "credential" not in str(error.value)
    receipt = json.loads((arguments["output_root"] / "run-001/receipt.json").read_text())
    assert receipt["status"] == "persistence_failed"


def test_forged_evaluator_result_is_rejected(tmp_path, monkeypatch, audit):
    arguments = inputs(tmp_path)
    def execute(self, request, directory):
        if request["operation"] == "candidate":
            artifact = deepcopy(arguments["baseline"])
            artifact.update(candidate_id=candidate_config_hash(arguments["config"]), candidate_version=arguments["config"]["candidate_model_version"])
            return stage({"protocol_version": runner.PROTOCOL_VERSION, "status": "ok", "result": artifact,
                          "candidate_config_hash": candidate_config_hash(arguments["config"])})
        result = process_request(request)
        result["result"]["evaluation_hash"] = "forged"
        return stage(result)
    monkeypatch.setattr(DockerExecutor, "execute", execute)
    assert runner.run_research_experiment(**arguments)["failure_reason"] == "frozen_evaluation_result_mismatch"


@pytest.mark.parametrize("kwargs", [{"cpus": float("nan")}, {"memory_mb": True}, {"timeout_seconds": 0}, {"output_bytes": 10**10}])
def test_resource_limits_reject_invalid_values(kwargs):
    with pytest.raises(ValueError):
        ResourceLimits(**kwargs)


def test_container_command_pins_image_and_enforces_isolation(tmp_path):
    command = DockerExecutor(IMAGE, ResourceLimits()).command("test", tmp_path)
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                 "--memory=512m", "--memory-swap=512m", "--pids-limit=64", "--restart=no", "--pull=never"):
        assert flag in command
    assert "docker.sock" not in " ".join(command)
    assert "--env" not in command
    assert command[-2:] == ["-m", "scripts.research_worker"]
    for image in ("latest", "name:tag", IMAGE + ";command"):
        with pytest.raises(ValueError):
            validate_image(image)


def test_local_disk_failure_does_not_prevent_terminal_audit(tmp_path, monkeypatch, audit):
    arguments, requests = inputs(tmp_path), []
    install_success(monkeypatch, arguments, requests)
    original, calls = runner._write_receipt, []
    def write(directory, value):
        calls.append(value["status"])
        if len(calls) > 2:
            raise OSError("synthetic disk full")
        original(directory, value)
    monkeypatch.setattr(runner, "_write_receipt", write)
    result = runner.run_research_experiment(**arguments)
    assert result["status"] == "candidate"
    assert result["receipt_updated"] is False
    assert audit[-1][1]["execution_metadata"]["local_receipt_write_failed"]
