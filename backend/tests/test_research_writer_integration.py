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
