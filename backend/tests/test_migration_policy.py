"""Artifact and approval gates must fail before a database command can execute."""
import importlib.util
import json
from pathlib import Path
import shutil
from datetime import datetime, timedelta, timezone

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('whatte_migrate', ROOT / 'scripts/migrate.py')
migrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrate)


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / 'migrations', tmp_path / 'migrations')
    return tmp_path


def test_declared_baseline_is_valid(root):
    _, declared = migrate.artifacts(root)
    assert set(declared) == {'V1__baseline.sql'}


@pytest.mark.parametrize('filename', ['V2__unreviewed.sql', 'beforeMigrate.sql', 'V1__baseline.sql.conf'])
def test_undeclared_sql_callbacks_and_overrides_are_rejected(root, filename):
    (root / 'migrations/sql' / filename).write_text('select 1;')
    with pytest.raises(ValueError, match='Undeclared'):
        migrate.artifacts(root)


def test_changed_baseline_is_rejected(root):
    with (root / 'migrations/sql/V1__baseline.sql').open('a') as file:
        file.write('\nselect 1;\n')
    with pytest.raises(ValueError, match='hash mismatch'):
        migrate.artifacts(root)


@pytest.mark.parametrize('change', [{'risk': 'unknown'}, {'transactional': False}])
def test_unclassified_and_nontransactional_migrations_are_rejected(root, change):
    path = root / 'migrations/manifest.json'
    manifest = json.loads(path.read_text())
    manifest['migrations'][0].update(change)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        migrate.artifacts(root)


def test_production_is_the_default_and_credentials_are_separate(monkeypatch):
    monkeypatch.delenv('MIGRATION_ENVIRONMENT', raising=False)
    monkeypatch.setenv('FLYWAY_URL', 'jdbc:postgresql://127.0.0.1:5432/test')
    monkeypatch.setenv('FLYWAY_USER', 'test')
    monkeypatch.setenv('FLYWAY_PASSWORD', 'test')
    assert migrate.target_environment()[0] == 'production'
    monkeypatch.setenv('FLYWAY_URL', 'jdbc:postgresql://127.0.0.1:5432/test?options=unsafe')
    with pytest.raises(ValueError, match='overrides'):
        migrate.target_environment()


@pytest.mark.parametrize('change', ['target', 'manifest', 'catalog', 'stale', 'no_restore', 'no_regular_backup'])
def test_approval_is_bound_to_review_and_backup(root, monkeypatch, change):
    monkeypatch.setenv('FLYWAY_URL', 'jdbc:postgresql://127.0.0.1:5432/test')
    receipt = {'action': 'baseline', 'authorized_by': 'test', 'authorization_reference': 'test',
               'target': 'jdbc:postgresql://127.0.0.1:5432/test',
               'manifest_sha256': migrate.digest(root / 'migrations/manifest.json'),
               'catalog_hash': 'catalog', 'backup': {'restore_verified': True, 'off_host_encrypted': True,
                   'sha256': 'a' * 64, 'reference': 'synthetic-test-only', 'regular_backup_process': 'test',
                   'verified_at': datetime.now(timezone.utc).isoformat()}}
    if change in {'target', 'catalog', 'manifest'}:
        receipt[{'catalog': 'catalog_hash', 'manifest': 'manifest_sha256'}.get(change, change)] = 'wrong'
    elif change == 'stale':
        receipt['backup']['verified_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    elif change == 'no_restore':
        receipt['backup']['restore_verified'] = False
    elif change == 'no_regular_backup':
        receipt['backup'].pop('regular_backup_process')
    path = root / 'approval.json'
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        migrate.approval(root, path, 'baseline', 'catalog')


def test_json_validation_failure_blocks_even_when_process_exits_zero(root, monkeypatch):
    for key in ('FLYWAY_URL', 'FLYWAY_USER', 'FLYWAY_PASSWORD'):
        monkeypatch.setenv(key, 'test')
    monkeypatch.setattr(migrate, 'docker_run', lambda *args, **kwargs: json.dumps({
        'validationSuccessful': False, 'errorDetails': {'errorCode': 'CHECKSUM_MISMATCH'}}))
    with pytest.raises(RuntimeError, match='reported failure'):
        migrate.flyway(root, 'validate')


def test_changed_verification_query_is_rejected(root):
    path = root / 'migrations/verification/catalog.sql'
    path.write_text('select 1;')
    with pytest.raises(ValueError, match='Verification artifact hash mismatch'):
        migrate.artifacts(root)


def test_valid_cached_approval_cannot_bypass_live_nas_failure(root, monkeypatch):
    import subprocess
    monkeypatch.setenv('FLYWAY_URL', 'jdbc:postgresql://127.0.0.1:5432/test')
    timestamp = datetime.now(timezone.utc).isoformat()
    config = root / 'backup.json'; config.write_text('{}')
    proof = root / 'restored.json'; proof.write_text(json.dumps({'sha256': 'a' * 64, 'verified_at': timestamp}))
    value = {'action': 'baseline', 'authorized_by': 'test', 'authorization_reference': 'test',
             'target': 'jdbc:postgresql://127.0.0.1:5432/test',
             'manifest_sha256': migrate.digest(root / 'migrations/manifest.json'), 'catalog_hash': 'catalog',
             'backup': {'restore_verified': True, 'off_host_encrypted': True, 'sha256': 'a' * 64,
                 'reference': 'synthetic', 'regular_backup_process': 'synthetic', 'verified_at': timestamp,
                 'config_path': str(config), 'config_sha256': migrate.digest(config),
                 'receipt_path': str(proof), 'receipt_sha256': migrate.digest(proof)}}
    path = root / 'approval.json'; path.write_text(json.dumps(value))
    monkeypatch.setattr(migrate.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, '', 'offline'))
    with pytest.raises(ValueError, match='production write blocked'):
        migrate.approval(root, path, 'baseline', 'catalog')
