"""Exercise release gates and failure recovery without production writes."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import deploy
from deploy_policy import eligible_run, ordering, requires_rollout

SHA = 'a' * 40
OLD = 'b' * 40
IMAGE = 'ghcr.io/shchukins/whatte-backend@sha256:' + 'c' * 64


def migration_output(rows):
    return json.dumps({'event': 'migration_started', 'action': 'info'}) + '\n' + json.dumps({
        'event': 'migration_succeeded', 'action': 'info', 'result': {'migrations': rows}})


def test_migration_cli_jsonl_contract_and_partial_failure():
    assert deploy.migration_outcome(migration_output([]), 'info') == {'migrations': []}
    for output in ('{"event":"migration_started","action":"info"}',
                   '{"event":"migration_failed","action":"info"}',
                   '{"migrations":[]}'):
        with pytest.raises(ValueError):
            deploy.migration_outcome(output, 'info')


def test_adapter_reads_actual_migration_cli_output(monkeypatch, capsys):
    result = {'migrations': [{'state': 'Pending', 'filepath': 'V2__change.sql'}]}
    monkeypatch.setattr(sys, 'argv', ['migrate.py', 'info'])
    monkeypatch.setattr(deploy.migrate, 'execute', lambda _args: result)
    assert deploy.migrate.main() == 0
    assert deploy.migration_outcome(capsys.readouterr().out, 'info') == result


def ci():
    return {'head_sha': SHA, 'head_branch': 'main', 'event': 'push',
            'path': '.github/workflows/backend-ci.yml', 'status': 'completed', 'conclusion': 'success'}


def jobs():
    return [{'name': name, 'conclusion': 'success'} for name in ('unit-tests', 'db-integration-tests', 'publish-release')]


@pytest.mark.parametrize('key,value', [('head_sha', OLD), ('head_branch', 'feature'),
                                      ('event', 'pull_request'), ('conclusion', 'failure'),
                                      ('status', 'in_progress'), ('path', 'other.yml')])
def test_ci_blocks_untrusted_or_incomplete_release(key, value):
    run = ci()
    run[key] = value
    with pytest.raises(ValueError):
        eligible_run(run, jobs(), SHA)


def test_all_required_jobs_must_pass():
    eligible_run(ci(), jobs(), SHA)
    for missing in range(3):
        checks = jobs()
        checks[missing]['conclusion'] = 'skipped'
        with pytest.raises(ValueError):
            eligible_run(ci(), checks, SHA)


def test_reordered_queue_cannot_deploy_old_or_divergent_release():
    ordering(SHA, SHA, OLD, lambda *_: True)
    with pytest.raises(ValueError, match='Stale'):
        ordering(OLD, SHA, OLD, lambda *_: True)
    with pytest.raises(ValueError, match='regress'):
        ordering(SHA, SHA, OLD, lambda *_: False)


@pytest.mark.parametrize('paths,expected', [(['README.md', 'docs/data/MIGRATIONS.md'], False),
                                          (['backend/README.md', 'ops/deploy/README.md'], False),
                                          (['backend/backend/prompt.md'], True),
                                          (['backend/templates/today.html'], True),
                                          (['migrations/sql/V2__change.sql'], True),
                                          (['compose.production.yaml'], True),
                                          (['scripts/deploy.py'], True)])
def test_documentation_only_skip_and_runtime_inputs(paths, expected):
    assert requires_rollout(paths) is expected


@pytest.fixture
def host(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setattr(deploy, 'STATE', state)
    monkeypatch.setattr(deploy, 'REPO', tmp_path)
    config = state / 'deployment.json'
    monkeypatch.setattr(deploy, 'CONFIG', config)
    creds = tmp_path / 'credentials.json'
    creds.write_text('{}')
    creds.chmod(0o600)
    config.write_text(json.dumps({'migration_credentials': str(creds), 'backup_config': 'private',
                                 'postgres_bind_address': '100.64.0.1'}))
    config.chmod(0o600)
    previous = {'git_sha': OLD, 'image': IMAGE, 'compose': 'previous-compose', 'env': 'previous-env'}
    (state / 'current.json').write_text(json.dumps(previous))
    manifest = {'git_sha': SHA, 'image': IMAGE, 'ci_run': 'ci', 'contract_version': 'whatte_release_v1',
                'files_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                 for name in ('compose.production.yaml', 'backend/requirements.lock', 'migrations/manifest.json', 'migrations/sql/V1__baseline.sql')}}
    calls = []
    database = {'Id': 'database-id', 'Mounts': ['preserved'], 'State': {'StartedAt': 'original'},
                'Config': {'Image': 'pgvector/pgvector:pg16-trixie'},
                'HostConfig': {'PortBindings': {'5432/tcp': [{'HostIp': '100.64.0.1'}]}}}
    def run(*args, **kwargs):
        calls.append(args)
        if args[:3] == ('git', 'rev-parse', 'origin/main'):
            return SHA
        if args[:3] == ('git', 'diff', '--name-only'):
            return 'backend/backend/app.py'
        if 'info' in args:
            return migration_output([])
        if 'create' in args:
            return '{"event":"backup_succeeded","result":{"sha256":"backup"}}'
        if args[-3:] == ('config', '--format', 'json'):
            return json.dumps({'services': {'postgres': {'image': database['Config']['Image'], 'ports': [{'host_ip': '100.64.0.1'}]}}})
        return '{}'
    monkeypatch.setattr(deploy, 'run', run)
    monkeypatch.setattr(deploy, 'inspect', lambda _: database)
    monkeypatch.setattr(deploy, 'health', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(deploy, 'verify_worker', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(deploy, 'worker_term_handler', lambda: True)
    monkeypatch.setattr(deploy, 'validate_compose', lambda *_args: None)
    monkeypatch.setattr(deploy, 'check_db', lambda _: None)
    monkeypatch.setattr(deploy.migrate, 'artifacts', lambda _: ({}, {}))
    monkeypatch.setattr(deploy.subprocess, 'run', lambda *_args, **_kwargs: type('Result', (), {'returncode': 0})())
    return state, calls, manifest, run


def test_missing_manifest_binding_blocks_deployment(host):
    state, calls, manifest, _ = host
    manifest['files_sha256'].pop('compose.production.yaml')
    with pytest.raises(ValueError, match='Incomplete'):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    assert not calls


def test_dry_run_does_not_backup_migrate_or_replace_services(host):
    state, calls, manifest, _ = host
    result = deploy.execute({'mode': 'dry-run', 'manifest': manifest}, ROOT)
    assert result['phase'] == 'dry_run'
    assert not any('migrate' in c or 'create' in c or 'up' in c or 'stop' in c or 'pull' in c for c in calls)
    assert json.loads((state / 'current.json').read_text())['git_sha'] == OLD


def test_backup_failure_blocks_all_application_changes(host, monkeypatch):
    state, calls, manifest, original = host
    def failed_backup(*args, **kwargs):
        if 'create' in args:
            raise RuntimeError('backup unavailable')
        return original(*args, **kwargs)
    monkeypatch.setattr(deploy, 'run', failed_backup)
    with pytest.raises(RuntimeError):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    assert json.loads((state / 'active.json').read_text())['phase'] == 'preflight_failed'
    assert not any('up' in c or 'stop' in c for c in calls)


def test_interrupted_phase_requires_reconciliation(host):
    state, calls, manifest, _ = host
    (state / 'active.json').write_text('{"phase":"rollout"}')
    with pytest.raises(ValueError, match='reconciliation'):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    assert not calls


def test_incompatible_pending_migration_cannot_stop_worker(host, monkeypatch):
    state, calls, manifest, original = host
    monkeypatch.setattr(deploy.migrate, 'artifacts', lambda _: ({}, {'V2__change.sql': {'old_app_compatible': False}}))
    def pending(*args, **kwargs):
        if 'info' in args:
            return migration_output([{'state': 'Pending', 'filepath': 'V2__change.sql'}])
        return original(*args, **kwargs)
    monkeypatch.setattr(deploy, 'run', pending)
    with pytest.raises(RuntimeError):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    assert not any('create' in c or 'up' in c or 'stop' in c for c in calls)


def prepared_rollout(host, monkeypatch):
    state, calls, manifest, original = host
    db = deploy.inspect('human-engine-postgres')
    pulled = {'Id': 'new-image', 'RepoDigests': [IMAGE], 'Config': {'Labels': {'org.opencontainers.image.revision': SHA}}}
    worker = {'State': {'ExitCode': 0, 'Running': True}}
    monkeypatch.setattr(deploy, 'inspect', lambda name: db if name == 'human-engine-postgres' else pulled if name == IMAGE else worker)
    monkeypatch.setattr(deploy, 'validate_compose', lambda *_: None)
    def run(*args, **kwargs):
        if args[-3:] == ('config', '--format', 'json'):
            calls.append(args)
            return json.dumps({'services': {'postgres': {'image': db['Config']['Image'], 'ports': [{'host_ip': '100.64.0.1'}]}}})
        return original(*args, **kwargs)
    monkeypatch.setattr(deploy, 'run', run)
    return run


def test_failed_migration_never_replaces_app_and_blocks_retry(host, monkeypatch):
    state, calls, manifest, _ = host
    original = prepared_rollout(host, monkeypatch)
    def fail(*args, **kwargs):
        if 'migrate' in args:
            calls.append(args)
            raise RuntimeError('transaction failed')
        return original(*args, **kwargs)
    monkeypatch.setattr(deploy, 'run', fail)
    with pytest.raises(RuntimeError):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    assert not any('stop' in c or 'up' in c for c in calls)
    assert json.loads((state / 'active.json').read_text())['phase'] == 'migration_failed'
    with pytest.raises(ValueError, match='reconciliation'):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)


def test_backend_failure_recovers_both_services_using_saved_config(host, monkeypatch):
    state, calls, manifest, _ = host
    prepared_rollout(host, monkeypatch)
    checks = []
    def health(sha, **kwargs):
        checks.append(sha)
        if sha == SHA:
            raise ValueError('new backend unhealthy')
    monkeypatch.setattr(deploy, 'health', health)
    with pytest.raises(RuntimeError):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    recovery = [c for c in calls if 'previous-compose' in c]
    assert any(c[-3:] == ('-d', '--no-deps', 'backend') for c in recovery)
    assert any(c[-3:] == ('-d', '--no-deps', 'worker') for c in recovery)
    assert checks[-1] == OLD
    assert json.loads((state / 'active.json').read_text())['phase'] == 'recovered'
    assert json.loads((state / 'current.json').read_text())['git_sha'] == OLD


def test_recovery_failure_requires_operator_and_preserves_previous_reference(host, monkeypatch):
    state, calls, manifest, _ = host
    original = prepared_rollout(host, monkeypatch)
    def fail(*args, **kwargs):
        if 'up' in args:
            calls.append(args)
            raise RuntimeError('compose failed')
        return original(*args, **kwargs)
    monkeypatch.setattr(deploy, 'run', fail)
    with pytest.raises(RuntimeError):
        deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    assert json.loads((state / 'active.json').read_text())['phase'] == 'recovery_failed'
    assert json.loads((state / 'current.json').read_text())['git_sha'] == OLD


def test_graceful_shutdown_does_not_claim_ingest_job(monkeypatch):
    from backend import worker
    processed = []
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    monkeypatch.setattr(worker, 'maybe_send_daily_readiness', lambda: worker.request_shutdown(None, None))
    monkeypatch.setattr(worker, 'maybe_schedule_next_day_recovery_prompts', lambda: None)
    monkeypatch.setattr(worker, 'maybe_reconcile_recent_rpe', lambda: None)
    monkeypatch.setattr(worker, 'process_one_strava_ingest_job', lambda: processed.append(True))
    worker.main()
    assert not processed


def test_shutdown_finishes_active_ingest_job(monkeypatch):
    from backend import worker
    processed = []
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    for name in ('maybe_send_daily_readiness', 'maybe_schedule_next_day_recovery_prompts', 'maybe_reconcile_recent_rpe'):
        monkeypatch.setattr(worker, name, lambda: None)
    def job():
        worker.request_shutdown(None, None)
        processed.append('completed')
        return {'message': 'no pending jobs'}
    monkeypatch.setattr(worker, 'process_one_strava_ingest_job', job)
    worker.main()
    assert processed == ['completed']


def test_host_lock_survives_parent_disconnect(tmp_path):
    import fcntl
    import os
    import time
    lock_path = tmp_path / 'deploy.lock'
    with open(lock_path, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.2)'],
                                 pass_fds=(lock.fileno(),), start_new_session=True)
    # Parent has closed its descriptor. The independent child still holds it.
    with open(lock_path, 'a') as contender:
        with pytest.raises(BlockingIOError):
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        child.wait(timeout=5)
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_forced_command_rejects_shell_and_forwarding_request(monkeypatch):
    spec = importlib.util.spec_from_file_location('ssh_gate', ROOT / 'ops/deploy/ssh_gate.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    for command in ('bash', 'scp -t /tmp', 'whatte-deploy-v1; bash', ''):
        monkeypatch.setenv('SSH_ORIGINAL_COMMAND', command)
        with pytest.raises(ValueError, match='fixed'):
            gate.main()


def test_success_records_coherent_release_without_touching_postgres(host, monkeypatch):
    state, calls, manifest, original = host
    prepared = prepared_rollout(host, monkeypatch)
    database = deploy.inspect('human-engine-postgres')
    image = {'Id': 'new-image', 'RepoDigests': [IMAGE], 'Config': {'Labels': {'org.opencontainers.image.revision': SHA}}}
    app = {'Id': 'app-id', 'Image': 'new-image', 'Config': {'Image': IMAGE}, 'Mounts': [],
           'State': {'Running': True, 'ExitCode': 0}, 'RestartCount': 0}
    monkeypatch.setattr(deploy, 'inspect', lambda name: database if name == 'human-engine-postgres' else image if name == IMAGE else app)
    def run(*args, **kwargs):
        if args[:2] == ('docker', 'exec'):
            calls.append(args)
            return json.dumps({'git_sha': SHA})
        if args[0] == 'curl':
            calls.append(args)
            return '401' if args[-1] == 'https://shchukin.de/today' else '404'
        return prepared(*args, **kwargs)
    monkeypatch.setattr(deploy, 'run', run)
    result = deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)
    assert result['phase'] == 'success'
    assert result['shared_image_verified'] and result['database_unchanged']
    assert json.loads((state / 'current.json').read_text())['git_sha'] == SHA
    assert not any(c[0] == 'docker' and any(action in c for action in ('down', 'restart', 'up', 'stop')) and c[-1] == 'postgres' for c in calls)


def test_docs_only_release_preserves_current_app_and_skips_backup(host, monkeypatch):
    state, calls, manifest, original = host
    def docs(*args, **kwargs):
        if args[:3] == ('git', 'diff', '--name-only'):
            return 'README.md\ndocs/architecture/PRODUCTION_DELIVERY.md'
        return original(*args, **kwargs)
    monkeypatch.setattr(deploy, 'run', docs)
    assert deploy.execute({'mode': 'deploy', 'manifest': manifest}, ROOT)['phase'] == 'docs_skipped'
    assert json.loads((state / 'current.json').read_text())['git_sha'] == OLD
    assert not any('create' in c or 'migrate' in c or 'up' in c or 'stop' in c for c in calls)


def test_worker_stop_uses_signal_handled_by_legacy_python_pid1(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy, 'inspect', lambda _: {'State': {'Running': True, 'ExitCode': 130}})
    monkeypatch.setattr(deploy, 'run', lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(deploy, 'worker_term_handler', lambda: False)
    monkeypatch.setattr(deploy, 'legacy_worker_idle', lambda: True)
    deploy.stop_worker()
    assert calls == [('docker', 'stop', '--signal', 'SIGINT', '--timeout', '60', 'human-engine-worker')]


def test_forced_worker_kill_remains_a_failure(monkeypatch):
    monkeypatch.setattr(deploy, 'inspect', lambda _: {'State': {'Running': True, 'ExitCode': 137}})
    monkeypatch.setattr(deploy, 'run', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(deploy, 'worker_term_handler', lambda: True)
    with pytest.raises(ValueError, match='graceful drain timeout'):
        deploy.stop_worker()


def test_already_stopped_worker_does_not_repeat_drain(monkeypatch):
    monkeypatch.setattr(deploy, 'inspect', lambda _: {'State': {'Running': False, 'ExitCode': 137}})
    monkeypatch.setattr(deploy, 'run', lambda *_args: pytest.fail('Stopped worker should not receive another signal'))
    deploy.stop_worker()


def test_legacy_busy_worker_is_not_interrupted(monkeypatch):
    monkeypatch.setattr(deploy, 'inspect', lambda _: {'State': {'Running': True}})
    monkeypatch.setattr(deploy, 'worker_term_handler', lambda: False)
    monkeypatch.setattr(deploy, 'legacy_worker_idle', lambda: False)
    monkeypatch.setattr(deploy.time, 'sleep', lambda _: None)
    monkeypatch.setattr(deploy, 'run', lambda *_args: pytest.fail('Busy legacy worker must not receive a signal'))
    with pytest.raises(ValueError, match='idle window'):
        deploy.stop_worker()


def test_legacy_idle_proof_must_be_recent_and_in_idle_sleep(monkeypatch):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    for event, seconds, age, expected in [('worker_idle', 10, 0, True), ('worker_idle', 10, 10, False),
                                          ('strava_ingest_job_processed', 10, 0, False), ('worker_idle', 1, 0, False)]:
        monkeypatch.setattr(deploy, 'run', lambda *_args: json.dumps({'event': event, 'sleep_seconds': seconds,
                            'timestamp': (now - timedelta(seconds=age)).isoformat()}))
        assert deploy.legacy_worker_idle() is expected
