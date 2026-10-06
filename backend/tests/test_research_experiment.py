from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.services import research_experiment
from backend.services.research_parameter_space import baseline_candidate_config


STARTED = datetime(2026, 10, 6, 7, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        self.calls.append((query, params))

    def fetchone(self):
        return next(self.rows)


class _Connection:
    def __init__(self, rows):
        self.cursor_value = _Cursor(rows)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True


def _create(**overrides):
    arguments = {
        "experiment_id": "experiment-001",
        "hypothesis": "A smaller freshness weight improves validation MAE.",
        "candidate_model_version": "readiness_parameter_candidate_v1",
        "candidate_config": baseline_candidate_config(),
        "dataset_version": "temporal_dataset_v1",
        "dataset_hash": "dataset-hash",
        "dataset_partition": "validation",
        "evaluator_version": "baseline_evaluator_v1",
        "evaluator_specification_hash": "metric-spec-hash",
        "started_at": STARTED,
    }
    arguments.update(overrides)
    return research_experiment.create_research_experiment(**arguments)


def test_create_persists_running_audit_record_and_config_fingerprint(monkeypatch):
    connection = _Connection([(17, STARTED, STARTED)])
    monkeypatch.setattr(research_experiment, "get_conn", lambda: connection)

    result = _create()

    assert result["id"] == 17
    assert result["status"] == "running"
    assert len(result["candidate_config_hash"]) == 64
    assert connection.committed is True
    query, params = connection.cursor_value.calls[0]
    assert "insert into research_experiment" in query
    assert params[-2:] == (STARTED, STARTED)


def test_create_rejects_self_reference_before_database_access(monkeypatch):
    monkeypatch.setattr(research_experiment, "get_conn", lambda: pytest.fail("database used"))

    with pytest.raises(ValueError, match="cannot reference itself"):
        _create(parent_experiment_id="experiment-001")


def test_terminal_candidate_stores_metrics_once_with_duration(monkeypatch):
    finished = STARTED + timedelta(seconds=2.345)
    connection = _Connection([
        (STARTED,),
        (17, STARTED, STARTED, finished, 2345),
    ])
    monkeypatch.setattr(research_experiment, "get_conn", lambda: connection)

    result = research_experiment.finish_research_experiment(
        experiment_id="experiment-001", status="candidate", finished_at=finished,
        metrics={"targets": {"post_workout_rpe": {"mae": 0.5}}},
    )

    assert result["status"] == "candidate"
    assert result["execution_duration_ms"] == 2345
    assert result["metrics"]["targets"]["post_workout_rpe"]["mae"] == 0.5
    assert connection.committed is True
    assert len(connection.cursor_value.calls) == 2
    assert "for update" in connection.cursor_value.calls[0][0]
    assert "update research_experiment" in connection.cursor_value.calls[1][0]


def test_failure_remains_auditable_without_metrics(monkeypatch):
    finished = STARTED + timedelta(seconds=1)
    connection = _Connection([(STARTED,), (17, STARTED, STARTED, finished, 1000)])
    monkeypatch.setattr(research_experiment, "get_conn", lambda: connection)

    result = research_experiment.finish_research_experiment(
        experiment_id="experiment-001", status="failed", finished_at=finished,
        failure_reason="candidate process timed out", failure_log_reference="runs/001.log",
    )

    assert result["metrics"] is None
    assert result["failure_reason"] == "candidate process timed out"
    assert result["failure_log_reference"] == "runs/001.log"


@pytest.mark.parametrize("status", ("running", "promoted", "complete"))
def test_finish_rejects_non_terminal_or_promotion_status(status):
    with pytest.raises(ValueError, match="status must be"):
        research_experiment.finish_research_experiment(
            experiment_id="experiment-001", status=status, metrics={}, finished_at=STARTED,
        )


def test_finish_rejects_result_mutation_shapes_before_database_access(monkeypatch):
    monkeypatch.setattr(research_experiment, "get_conn", lambda: pytest.fail("database used"))

    with pytest.raises(ValueError, match="cannot store failure metadata"):
        research_experiment.finish_research_experiment(
            experiment_id="experiment-001", status="rejected", metrics={},
            failure_reason="not allowed", finished_at=STARTED,
        )
    with pytest.raises(ValueError, match="cannot store metrics"):
        research_experiment.finish_research_experiment(
            experiment_id="experiment-001", status="failed", metrics={},
            failure_reason="failed", finished_at=STARTED,
        )


def test_service_has_no_production_domain_write_surface():
    source_path = Path(__file__).parents[1] / "backend/services/research_experiment.py"
    source = source_path.read_text(encoding="utf-8")

    assert "insert into research_experiment" in source
    assert "update research_experiment" in source
    for forbidden in ("readiness_daily", "activity_subjective_feedback", "strava_activity_raw"):
        assert forbidden not in source


def test_migration_makes_terminal_metadata_immutable_and_blocks_deletion():
    migration_path = Path(__file__).parents[2] / "db-init/018_research_experiment.sql"
    migration = migration_path.read_text(encoding="utf-8")

    assert "terminal research experiment rows are immutable" in migration
    assert "research experiment audit rows cannot be deleted" in migration
    assert "research experiment must be created as running" in migration
    assert "new.status not in ('candidate', 'rejected', 'failed')" in migration


@pytest.mark.parametrize("overrides", [
    {"candidate_config": {"freshness_weight": 0.5}},
    {"candidate_config": baseline_candidate_config() | {"unknown": 1}},
    {"candidate_model_version": "other"},
    {"dataset_version": "other"},
    {"evaluator_version": "other"},
])
def test_create_validates_config_and_version_binding_before_database_access(monkeypatch, overrides):
    monkeypatch.setattr(research_experiment, "get_conn", lambda: pytest.fail("database used"))
    with pytest.raises(ValueError):
        _create(**overrides)


def test_create_stores_search_space_version_and_canonical_hash(monkeypatch):
    from backend.services.research_parameter_space import candidate_config_hash

    connection = _Connection([(17, STARTED, STARTED)])
    monkeypatch.setattr(research_experiment, "get_conn", lambda: connection)
    config = baseline_candidate_config()
    result = _create(candidate_config=config)
    stored = connection.cursor_value.calls[0][1][5]
    assert '"search_space_version":"readiness_parameter_space_v1"' in stored
    assert result["candidate_config_hash"] == candidate_config_hash(config)
