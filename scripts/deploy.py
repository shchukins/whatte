"""Host deployment engine. Must be invoked by the locked, CI-verifying SSH gate."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request
from deploy_policy import ordering, requires_rollout
from release_manifest import validate_compose, IMAGE_PATTERN
import migrate

REPO = Path('/srv/human-engine')
STATE = Path('/home/sergey/.config/whatte-release')
CONFIG = STATE / 'deployment.json'


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with open(temporary, 'w') as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run(*args, cwd=REPO, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
    if result.returncode:
        # Command output may contain env values, user data or credentials.
        raise RuntimeError('Subprocess failed: ' + Path(args[0]).name)
    return result.stdout.strip()


def inspect(name):
    return json.loads(run('docker', 'inspect', name))[0]


def http(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def health(sha, public=False):
    base = 'https://api.shchukin.de' if public else 'http://127.0.0.1:8000'
    for attempt in range(30):
        try:
            if http(base + '/healthz') != {'ok': True} or http(base + '/version') != {'git_sha': sha}:
                raise ValueError('Health/revision mismatch')
            if not public and http(base + '/dbz') != {'db': 'ok'}:
                raise ValueError('Database health failed')
            return
        except (OSError, ValueError):
            if attempt == 29:
                raise RuntimeError('Health/database/revision verification failed') from None
            time.sleep(1)


def verify_worker(sha, require_start=True):
    instance = inspect('human-engine-worker')
    revision = json.loads(run('docker', 'exec', instance['Id'], 'python', '-c',
                              'import json; from backend.release import RELEASE; print(json.dumps(RELEASE))'))
    if revision != {'git_sha': sha} or not instance['State']['Running']:
        raise ValueError('Worker identity/state mismatch')
    for attempt in range(30):
        events = []
        logs = subprocess.run(['docker', 'logs', '--tail', '100', 'human-engine-worker'], capture_output=True, text=True, check=True)
        for line in (logs.stdout + '\n' + logs.stderr).splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        if any(e.get('level') in {'ERROR', 'CRITICAL'} for e in events):
            raise ValueError('Worker error after rollout')
        if ((not require_start or any(e.get('event') == 'worker_started' and e.get('git_sha') == sha for e in events))
                and any(e.get('event') in {'worker_idle', 'strava_ingest_job_processed'} for e in events)):
            return
        time.sleep(1)
    raise ValueError('Worker startup/progress not verified')


def check_db(original):
    current = inspect('human-engine-postgres')
    if any(current[key] != original[key] for key in ('Id', 'Mounts')) or current['State']['StartedAt'] != original['State']['StartedAt']:
        raise ValueError('PostgreSQL identity/data mounts changed')


def execute(request, source):
    if request.get('mode') not in {'dry-run', 'deploy'}:
        raise ValueError('Invalid deployment mode')
    if CONFIG.stat().st_mode & 0o077:
        raise ValueError('Deployment configuration must be private')
    config = json.loads(CONFIG.read_text())
    manifest = request['manifest']
    sha, image = manifest['git_sha'], manifest['image']
    if not re.fullmatch('[0-9a-f]{40}', sha) or not re.fullmatch(IMAGE_PATTERN, image):
        raise ValueError('Immutable GHCR reference required')
    expected_files = {'compose.production.yaml', 'backend/requirements.lock', 'migrations/manifest.json', 'migrations/sql/V1__baseline.sql'}
    if manifest.get('contract_version') != 'whatte_release_v1' or set(manifest['files_sha256']) != expected_files:
        raise ValueError('Incomplete release manifest')
    previous = json.loads((STATE / 'current.json').read_text())
    active = STATE / 'active.json'
    if active.exists() and json.loads(active.read_text())['phase'] not in {'success', 'dry_run', 'docs_skipped', 'recovered', 'preflight_failed'}:
        raise ValueError('Interrupted deployment needs operator reconciliation')
    record = {'git_sha': sha, 'image': image, 'previous_sha': previous['git_sha'],
              'previous_image': previous['image'], 'ci_run': manifest['ci_run'],
              'mode': request['mode'], 'started_at': datetime.now(timezone.utc).isoformat()}
    def phase(value):
        record['phase'] = value
        write_json(active, record)
        write_json(STATE / ('delivery-' + sha + '-' + request['mode'] + '.json'), record)
    phase('preflight')
    changed_app = False
    schema_safe = False
    try:
        ordering(sha, run('git', 'rev-parse', 'origin/main'), previous['git_sha'],
                 lambda old, new: subprocess.run(['git', 'merge-base', '--is-ancestor', old, new], cwd=REPO).returncode == 0)
        for name, expected in manifest['files_sha256'].items():
            if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Release artifact hash mismatch')
        paths = run('git', 'diff', '--name-only', previous['git_sha'], sha).splitlines()
        if not requires_rollout(paths) and sha != previous['git_sha']:
            phase('docs_skipped')
            return record
        db = inspect('human-engine-postgres')
        health(previous['git_sha'])
        verify_worker(previous['git_sha'], require_start=False)
        migration_env = os.environ.copy()
        # Private JSON credentials avoid shell sourcing and secret output.
        credentials_path = Path(config['migration_credentials'])
        if credentials_path.stat().st_mode & 0o077:
            raise ValueError('Migration credentials must be private')
        credentials = json.loads(credentials_path.read_text())
        if set(credentials) - {'FLYWAY_URL', 'FLYWAY_USER', 'FLYWAY_PASSWORD', 'MIGRATION_DOCKER_NETWORK'}:
            raise ValueError('Unexpected migration environment override')
        migration_env.update(credentials, MIGRATION_ENVIRONMENT='production')
        migration_script = str(source / 'scripts/migrate.py')
        run('python3', migration_script, 'validate', env=migration_env)
        info = json.loads(run('python3', migration_script, 'info', env=migration_env))
        pending = [row for row in info.get('migrations', []) if row.get('state') == 'Pending']
        _, declared = migrate.artifacts(source)
        schema_safe = all(declared[Path(row['filepath']).name].get('old_app_compatible') is True for row in pending)
        if not schema_safe:
            raise ValueError('Incompatible migrations need a separate approved maintenance procedure')
        approval = config.get('migration_approval')
        if pending:
            saved_env = os.environ.copy()
            try:
                os.environ.update(migration_env)
                catalog_hash = migrate.canonical_hash(json.loads(migrate.psql(migrate.target_environment()[1], (source / 'migrations/verification/catalog.sql').read_text())))
                receipt = migrate.approval(source, approval, 'migrate', catalog_hash)
                for row in pending:
                    item = declared[Path(row['filepath']).name]
                    if item['risk'] != 'compatible' and receipt.get('approved_migrations', {}).get(item['file']) != item['sha256']:
                        raise ValueError('Risky migration requires exact approval')
            finally:
                os.environ.clear()
                os.environ.update(saved_env)
        render_env = {**os.environ, 'WHATTE_IMAGE': image, 'POSTGRES_BIND_ADDRESS': config['postgres_bind_address']}
        rendered = json.loads(run('docker', 'compose', '--project-directory', str(REPO),
                                  '-p', 'human-engine', '-f', str(source / 'compose.production.yaml'),
                                  'config', '--format', 'json', env=render_env))
        validate_compose(rendered, image)
        if (rendered['services']['postgres']['image'] != db['Config']['Image']
                or rendered['services']['postgres']['ports'][0]['host_ip'] != db['HostConfig']['PortBindings']['5432/tcp'][0]['HostIp']):
            raise ValueError('Database configuration parity mismatch')
        if request['mode'] == 'dry-run':
            record.update(pending_migrations=len(pending), schema_compatible=True, database_unchanged=True)
            check_db(db)
            phase('dry_run')
            return record
        # Fresh encrypted off-host backup before every rollout. This is integrity
        # evidence; pending SQL additionally requires an exact restore receipt.
        backup = json.loads(run('python3', str(source / 'scripts/postgres_backup.py'), 'create', '--config', config['backup_config']))
        if backup.get('event') != 'backup_succeeded':
            raise ValueError('Backup policy failed')
        record['backup_sha256'] = backup['result']['sha256']
        phase('backup_verified')
        run('docker', 'pull', image)
        pulled = inspect(image)
        if pulled['Config']['Labels'].get('org.opencontainers.image.revision') != sha or image not in pulled['RepoDigests']:
            raise ValueError('Pulled image revision/digest mismatch')
        # Save the complete selected config outside mutable checkout for rollback.
        directory = STATE / 'releases' / sha
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        compose_file = directory / 'compose.yaml'
        compose_file.write_bytes((source / 'compose.production.yaml').read_bytes())
        env_file = directory / 'release.env'
        env_file.write_text('WHATTE_IMAGE=' + image + '\nPOSTGRES_BIND_ADDRESS=' + config['postgres_bind_address'] + '\n')
        env_file.chmod(0o600)
        compose = ['docker', 'compose', '--project-directory', str(REPO), '-p', 'human-engine', '--env-file', str(env_file), '-f', str(compose_file)]
        rendered = json.loads(run(*compose, 'config', '--format', 'json'))
        validate_compose(rendered, image)
        if (rendered['services']['postgres']['image'] != db['Config']['Image']
                or rendered['services']['postgres']['ports'][0]['host_ip'] != db['HostConfig']['PortBindings']['5432/tcp'][0]['HostIp']):
            raise ValueError('Database configuration parity mismatch')
        run('docker', 'run', '--rm', '--network', 'human-engine_default', '--env-file', str(REPO / '.env'),
            '-e', 'EXPECTED_SHA=' + sha, image, 'python', '-c',
            'import os; from fastapi.testclient import TestClient; from backend.app import app; import backend.worker; c=TestClient(app); assert c.get("/dbz").json()=={"db":"ok"}; assert c.get("/version").json()=={"git_sha":os.environ["EXPECTED_SHA"]}')
        phase('migrations')
        migrate_args = ['python3', migration_script, 'migrate']
        if pending:
            migrate_args += ['--approval-file', approval]
        run(*migrate_args, env=migration_env)
        phase('rollout')
        changed_app = True
        run(*compose, 'stop', '-t', '60', 'worker')
        if inspect('human-engine-worker')['State'].get('ExitCode') == 137:
            raise ValueError('Worker exceeded graceful drain timeout')
        run(*compose, 'up', '-d', '--no-deps', 'backend')
        health(sha)
        run(*compose, 'up', '-d', '--no-deps', 'worker')
        verify_worker(sha)
        for name in ('backend', 'worker'):
            instance = inspect('human-engine-' + name)
            if (instance['Image'] != pulled['Id'] or instance['Config']['Image'] != image
                    or instance['Mounts'] or not instance['State']['Running'] or instance['RestartCount']):
                raise ValueError('Incoherent application release')
            revision = json.loads(run('docker', 'exec', instance['Id'], 'python', '-c', 'import json; from backend.release import RELEASE; print(json.dumps(RELEASE))'))
            if revision != {'git_sha': sha}:
                raise ValueError('Container revision mismatch')
        health(sha, public=True)
        for url, status in [('https://shchukin.de/today', '401'), ('https://api.shchukin.de/today', '404')]:
            if run('curl', '--max-time', '15', '-sS', '-o', '/dev/null', '-w', '%{http_code}', url) != status:
                raise ValueError('Protected route boundary changed')
        check_db(db)
        record.update(database_unchanged=True, shared_image_verified=True, worker_verified=True,
                      local_health=True, public_health=True, route_boundaries=True,
                      completed_at=datetime.now(timezone.utc).isoformat())
        # The running digest is authoritative; checkout is updated only after QA.
        phase('committing')
        run('git', 'merge', '--ff-only', sha)
        write_json(directory / 'manifest.json', manifest)
        write_json(STATE / 'current.json', {**manifest, 'compose': str(compose_file), 'env': str(env_file)})
        phase('success')
        return record
    except Exception as error:
        record['failure_type'] = type(error).__name__
        if changed_app and schema_safe:
            phase('recovery')
            recovery = ['docker', 'compose', '--project-directory', str(REPO), '-p', 'human-engine', '--env-file', previous['env'], '-f', previous['compose']]
            try:
                run(*recovery, 'stop', '-t', '60', 'worker')
                run(*recovery, 'up', '-d', '--no-deps', 'backend')
                health(previous['git_sha'])
                run(*recovery, 'up', '-d', '--no-deps', 'worker')
                verify_worker(previous['git_sha'])
                check_db(db)
                write_json(STATE / 'current.json', previous)
                phase('recovered')
            except Exception:
                phase('recovery_failed')
        else:
            phase('preflight_failed' if record['phase'] not in {'migrations', 'rollout'} else 'migration_failed')
        raise RuntimeError('Deployment failed; inspect durable host outcome') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(execute(json.loads(args.request.read_text()), args.source)))
    except Exception:
        print(json.dumps({'phase': 'failed', 'operator_action': 'inspect active.json and reconcile before retry'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
