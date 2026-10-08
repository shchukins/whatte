"""Real SQL grants and lifecycle checks on a disposable integration database."""

import os
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from backend.services.research_experiment import create_research_experiment, finish_research_experiment
from backend.services.research_parameter_space import baseline_candidate_config
from backend.services.research_writer import research_writer_connection

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="Set RUN_DB_TESTS=1 on a disposable schema")


@pytest.fixture
def writer_dsn():
    role, password = "research_test_" + uuid.uuid4().hex, uuid.uuid4().hex
    admin_dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("create role {} login password {} inherit").format(sql.Identifier(role), sql.Literal(password)))
        admin.execute(sql.SQL("grant whatte_research_writer to {}").format(sql.Identifier(role)))
    yield make_conninfo(admin_dsn, user=role, password=password)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
        admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))


def test_research_writer_can_record_failure_but_cannot_mutate_production(writer_dsn):
    factory = lambda: research_writer_connection(writer_dsn)
    experiment_id = "integration-" + uuid.uuid4().hex
    config = baseline_candidate_config()
    create_research_experiment(experiment_id=experiment_id, hypothesis="SQL permission verification",
                               candidate_model_version=config["candidate_model_version"], candidate_config=config,
                               dataset_version=config["dataset_version"], dataset_hash="synthetic",
                               dataset_partition="validation", evaluator_version=config["evaluator_version"],
                               evaluator_specification_hash="synthetic", connection_factory=factory)
    result = finish_research_experiment(experiment_id=experiment_id, status="failed",
                                       failure_reason="synthetic_timeout", execution_metadata={"exit_code": 137},
                                       connection_factory=factory)
    assert result["status"] == "failed"
    with factory() as conn:
        for statement in ("update readiness_daily set version=version where false",
                          "delete from activity_subjective_feedback where false",
                          "insert into strava_activity_raw default values"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)
            conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            conn.execute("update research_experiment set execution_metadata='{}'::jsonb where experiment_id=%s", (experiment_id,))
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("delete from research_experiment where experiment_id=%s", (experiment_id,))
        conn.rollback()
    with pytest.raises(ValueError, match="running research experiment not found"):
        finish_research_experiment(experiment_id=experiment_id, status="failed", failure_reason="repeat", connection_factory=factory)
    with pytest.raises(psycopg.errors.UniqueViolation):
        create_research_experiment(experiment_id=experiment_id, hypothesis="repeat",
                                   candidate_model_version=config["candidate_model_version"], candidate_config=config,
                                   dataset_version=config["dataset_version"], dataset_hash="synthetic",
                                   dataset_partition="validation", evaluator_version=config["evaluator_version"],
                                   evaluator_specification_hash="synthetic", connection_factory=factory)


def test_production_admin_credentials_are_rejected():
    with pytest.raises(ValueError, match="research_writer_role_required"):
        research_writer_connection(os.environ["DATABASE_URL"])

@pytest.mark.skipif(os.getenv("RUN_DOCKER_TESTS") != "1", reason="Needs disposable PostgreSQL and Linux Docker")
def test_real_prediction_runner_records_terminal_audit_with_dedicated_writer(writer_dsn, tmp_path):
    from pathlib import Path
    import subprocess
    from test_recovery_prediction import prepared
    import json
    import sys
    dataset, state, config, baseline = prepared()
    config.update(freshness_weight=0.8, recovery_evidence_weight=0.2)
    repo = Path(__file__).resolve().parents[2]
    built = subprocess.run(["docker", "build", "-q", "-f", str(repo / "backend/Dockerfile.research"),
                            str(repo / "backend")], check=True, capture_output=True, text=True, timeout=180)
    image = built.stdout.strip().splitlines()[-1]
    experiment = "model-integration-" + uuid.uuid4().hex
    try:
        paths = {}
        for name, value in (("config",config),("dataset",dataset),("learned-state",state),("baseline",baseline)):
            paths[name] = tmp_path/(name+".json")
            paths[name].write_text(json.dumps(value))
            paths[name].chmod(0o600)
        command = [sys.executable,"-m","scripts.run_research_experiment"]
        for name, path in paths.items():
            command.extend(["--"+name,str(path)])
        command.extend(["--experiment-id",experiment,"--hypothesis","Real model Docker SQL CLI fixture",
                        "--image",image,"--output-root",str(tmp_path/"private")])
        result = subprocess.run(command,cwd=repo/"backend",
                                env={**os.environ,"WHATTE_RESEARCH_DATABASE_URL":writer_dsn},
                                capture_output=True,text=True,check=True,timeout=180)
        assert json.loads(result.stdout)["status"] == "candidate"
        with research_writer_connection(writer_dsn) as conn:
            row = conn.execute("select status, candidate_config_hash, execution_metadata from research_experiment where experiment_id=%s",
                               (experiment,)).fetchone()
            assert row[0] == "candidate"
            assert row[2]["coverage"]["paired_days"] == 20
            assert row[2]["learned_state_hash"] == config["learned_state_hash"]
            assert all(s["cleanup_succeeded"] for s in row[2]["stages"])
    finally:
        subprocess.run(["docker","image","rm",image],check=True,capture_output=True,timeout=30)
