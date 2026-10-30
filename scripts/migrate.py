#!/usr/bin/env python3
"""Restricted, SQL-first Flyway entrypoint; never called by application startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
FLYWAY_IMAGE = 'redgate/flyway@sha256:0680d54cfd6a51369456dff902f62f1a0e4b87af00c92d6699ce4c3a3724eddb'
POSTGRES_IMAGE = 'mirror.gcr.io/pgvector/pgvector@sha256:41599f76505f3a9450355e34c83a4fd215a8099ea66fcb8b38049b15da155ee7'
RISKS = {'compatible', 'destructive', 'backfill', 'long_running', 'baseline'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def artifacts(root):
    manifest = json.loads((root / 'migrations/manifest.json').read_text())
    if manifest.get('format_version') != 1:
        raise ValueError('Unsupported migration manifest version')
    declared = {item['file']: item for item in manifest['migrations']}
    if len(declared) != len(manifest['migrations']):
        raise ValueError('Duplicate migration declaration')
    for name, sha in manifest['verification_sha256'].items():
        if not name.startswith('verification/') or '..' in Path(name).parts:
            raise ValueError('Invalid verification artifact path')
        if digest(root / 'migrations' / name) != sha:
            raise ValueError('Verification artifact hash mismatch')
    actual = {p.name for p in (root / 'migrations/sql').iterdir()}
    if actual != declared.keys():
        raise ValueError('Undeclared migration, callback or configuration file')
    versions = set()
    for name, item in declared.items():
        match = re.fullmatch(r'V([1-9][0-9]*)__[a-z0-9_]+\.sql', name)
        if not match or match[1] in versions or item['risk'] not in RISKS:
            raise ValueError('Invalid migration name, duplicate version or risk classification')
        versions.add(match[1])
        if item['sha256'] != digest(root / 'migrations/sql' / name):
            raise ValueError(f'Migration artifact hash mismatch: {name}')
        if item.get('transactional') is not True:
            raise ValueError('Nontransactional migrations require a separate approved procedure')
        # Transaction control must stay with Flyway. This is a conservative lint,
        # not a SQL risk classifier; human classification/review is mandatory.
        sql = (root / 'migrations/sql' / name).read_text()
        if re.search(r'(?mi)^\s*(BEGIN|COMMIT|ROLLBACK)\s*;', sql):
            raise ValueError('Embedded transaction control is forbidden')
        if item['risk'] == 'compatible' and item.get('old_app_compatible') is not True:
            raise ValueError('Compatible migration needs explicit old-app compatibility evidence')
    baseline = declared.get('V1__baseline.sql')
    if not baseline or baseline['risk'] != 'baseline':
        raise ValueError('V1 baseline must be declared')
    expected = root / 'migrations/verification/expected_catalog.json'
    if digest(expected) != manifest['baseline_catalog_sha256']:
        raise ValueError('Baseline catalog artifact hash mismatch')
    return manifest, declared


def target_environment():
    mode = os.environ.get('MIGRATION_ENVIRONMENT', 'production')
    if mode not in {'production', 'ci', 'development'}:
        raise ValueError('Unknown MIGRATION_ENVIRONMENT')
    url = os.environ.get('FLYWAY_URL', '')
    target = urlparse(url.removeprefix('jdbc:'))
    if not url.startswith('jdbc:postgresql://') or not target.hostname or not target.path.strip('/'):
        raise ValueError('FLYWAY_URL must identify a PostgreSQL database')
    if target.username or target.password or target.query or target.fragment:
        raise ValueError('Use separate credentials; JDBC query overrides are forbidden')
    for name in ('FLYWAY_USER', 'FLYWAY_PASSWORD'):
        if not os.environ.get(name):
            raise ValueError(f'{name} must be supplied through a protected environment')
    return mode, target


def docker_run(image, args, *, mounts=(), variables=None, stdin=None):
    env = os.environ.copy()
    env.update(variables or {})
    cmd = ['docker', 'run', '--rm', '--network', os.environ.get('MIGRATION_DOCKER_NETWORK', 'host')]
    if os.environ.get('MIGRATION_RUN_ID'):
        cmd += ['--label', 'whatte.migration.run=' + os.environ['MIGRATION_RUN_ID']]
    if stdin is not None:
        cmd.append('-i')
    for source, dest in mounts:
        cmd += ['-v', f'{source}:{dest}:ro']
    for name in variables or {}:
        cmd += ['-e', name]
    result = subprocess.run(cmd + [image] + args, input=stdin, text=True, capture_output=True, env=env)
    if result.returncode:
        # Avoid emitting connection URLs, credentials or SQL row values on error.
        try:
            error = json.loads(result.stdout).get('error', {})
        except ValueError:
            error = {}
        raise RuntimeError(f'{image.split("@")[0]} failed (exit {result.returncode}, '
                           f'code={error.get("errorCode", "unknown")}, sqlstate={error.get("sqlState", "unknown")})')
    return result.stdout


def psql(target, sql):
    return docker_run(POSTGRES_IMAGE, ['psql', '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1'],
                      variables={'PGHOST': target.hostname, 'PGPORT': str(target.port or 5432),
                                 'PGDATABASE': target.path.strip('/'), 'PGUSER': os.environ['FLYWAY_USER'],
                                 'PGPASSWORD': os.environ['FLYWAY_PASSWORD']}, stdin=sql)


def flyway(root, action, baseline_hash=None):
    args = ['-outputType=json', '-locations=filesystem:/flyway/sql', '-schemas=public',
            '-defaultSchema=public', '-table=flyway_schema_history', '-baselineOnMigrate=false',
            '-cleanDisabled=true', '-outOfOrder=false', '-validateOnMigrate=true',
            '-validateMigrationNaming=true', '-placeholderReplacement=false',
            '-executeInTransaction=true', '-mixed=false', '-lockRetryCount=5',
            '-connectRetries=0', '-baselineVersion=1',
            '-initSql=SET lock_timeout = \'5s\'; SET statement_timeout = \'120s\'']
    if baseline_hash:
        args.append(f'-baselineDescription=Whatte V1 sha256={baseline_hash}')
    if action == 'validate':
        # Preflight runs before migrate: declared pending versions are expected.
        # Keep Flyway's default future-version tolerance and all applied checksum,
        # missing-file and failed-migration checks; only add pending to validation.
        args.append('-ignoreMigrationPatterns=*:future,*:pending')
    args.append(action)
    output = docker_run(FLYWAY_IMAGE, args, mounts=[(root / 'migrations/sql', '/flyway/sql')],
                        variables={**{k: os.environ[k] for k in ('FLYWAY_URL', 'FLYWAY_USER', 'FLYWAY_PASSWORD')},
                                   'REDGATE_DISABLE_TELEMETRY': 'true'})
    result = json.loads(output)
    # Flyway 11's JSON validate command can exit 0 while reporting an invalid
    # checksum. Both process status and structured outcome must gate delivery.
    if (result.get('validationSuccessful') is False or result.get('success') is False
            or result.get('error') or result.get('errorDetails') or result.get('exception')
            or result.get('licenseFailed') is True):
        raise RuntimeError(f'Flyway {action} reported failure: '
                           + str((result.get('errorDetails') or {}).get('errorCode', 'operation_failed')))
    return result


def approval(root, filename, action, catalog_hash):
    if not filename:
        raise ValueError('Production writes require a reviewed approval receipt')
    receipt = json.loads(Path(filename).read_text())
    if (receipt.get('action') != action or not receipt.get('authorized_by') or not receipt.get('authorization_reference')
            or receipt.get('target') != os.environ['FLYWAY_URL']
            or receipt.get('manifest_sha256') != digest(root / 'migrations/manifest.json')
            or receipt.get('catalog_hash') != catalog_hash):
        raise ValueError('Approval does not match action, target, artifacts or reviewed catalog')
    backup = receipt.get('backup', {})
    if not (backup.get('restore_verified') is True and backup.get('off_host_encrypted') is True
            and re.fullmatch(r'[0-9a-f]{64}', backup.get('sha256', ''))
            and backup.get('reference') and backup.get('regular_backup_process')):
        raise ValueError('Verified restorable off-host backup and owned regular process are required')
    verified_at = datetime.fromisoformat(backup['verified_at'])
    if verified_at.tzinfo is None:
        raise ValueError('Backup verification timestamp must include a timezone')
    age = (datetime.now(timezone.utc) - verified_at).total_seconds()
    if not 0 <= age <= 86400:
        raise ValueError('Backup restore verification must be at most 24h old')
    # Recheck receiving-side NFS and the actual NAS archive before any SQL write;
    # an operator's cached boolean cannot authorize writes while NAS is offline.
    config = Path(backup['config_path'])
    proof = Path(backup['receipt_path'])
    if digest(config) != backup['config_sha256'] or digest(proof) != backup['receipt_sha256']:
        raise ValueError('Backup configuration or restore proof changed after review')
    restored = json.loads(proof.read_text())
    if restored.get('sha256') != backup['sha256'] or restored.get('verified_at') != backup['verified_at']:
        raise ValueError('Approval does not identify the verified backup archive')
    result = subprocess.run([sys.executable, str(root / 'scripts/postgres_backup.py'), 'verify',
                             '--config', str(config), '--receipt', str(proof)],
                            text=True, capture_output=True, timeout=240)
    if result.returncode:
        raise ValueError('Live NAS/backup verification failed; production write blocked')
    outcome = json.loads(result.stdout)
    if (outcome.get('event') != 'backup_succeeded'
            or outcome.get('result', {}).get('sha256') != backup['sha256']):
        raise ValueError('Invalid live backup verification outcome')
    return receipt


def verify_catalog(root, target):
    actual = json.loads(psql(target, (root / 'migrations/verification/catalog.sql').read_text()))
    expected = json.loads((root / 'migrations/verification/expected_catalog.json').read_text())
    differences = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k))
    if differences:
        raise ValueError('Catalog mismatch: ' + ', '.join(differences[:20]))
    return canonical_hash(actual)


def execute(args, root=ROOT):
    _, declared = artifacts(root)
    mode, target = target_environment()
    baseline_hash = declared['V1__baseline.sql']['sha256']
    if args.action == 'verify-baseline':
        catalog_hash = verify_catalog(root, target)
        checks = json.loads(psql(target, (root / 'migrations/verification/backfill_checks.sql').read_text()))
        if any(value != 0 for value in checks.values()):
            raise ValueError('Historical backfill postconditions need explicit reconciliation')
        return {'catalog_hash': catalog_hash, 'backfill_violations': checks}
    if args.action == 'baseline':
        catalog_hash = verify_catalog(root, target)
        checks = json.loads(psql(target, (root / 'migrations/verification/backfill_checks.sql').read_text()))
        if any(value != 0 for value in checks.values()):
            raise ValueError('Baseline backfill verification failed')
        approval(root, args.approval_file, 'baseline', catalog_hash)
        if psql(target, "select to_regclass('public.flyway_schema_history') is not null;").strip() == 't':
            raise ValueError('History already exists; baseline adoption is a one-time operation')
        return flyway(root, 'baseline', baseline_hash)
    info = flyway(root, 'info')
    migrations = info.get('migrations', [])
    for row in migrations:
        if row.get('version') == '1' and row.get('type') == 'BASELINE':
            if row.get('description') != f'Whatte V1 sha256={baseline_hash}':
                raise ValueError('Skipped V1 artifact differs from recorded baseline hash')
    if args.action == 'info':
        return info
    if args.action == 'migrate':
        pending = [row for row in migrations if row.get('state') == 'Pending']
        if mode == 'production':
            applied = [row for row in migrations if row.get('version') == '1' and row.get('state') in {'Baseline', 'Success'}]
            if not applied:
                raise ValueError('Existing production must explicitly adopt V1; automatic initialization is forbidden')
            if pending:
                catalog_hash = canonical_hash(json.loads(psql(target, (root / 'migrations/verification/catalog.sql').read_text())))
                receipt = approval(root, args.approval_file, 'migrate', catalog_hash)
                approved = receipt.get('approved_migrations', {})
                for row in pending:
                    item = declared[Path(row['filepath']).name]
                    if item['risk'] != 'compatible' and approved.get(item['file']) != item['sha256']:
                        raise ValueError('Risky migration lacks exact artifact approval')
    return flyway(root, args.action)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['info', 'validate', 'migrate', 'verify-baseline', 'baseline'])
    parser.add_argument('--approval-file')
    args = parser.parse_args()
    try:
        print(json.dumps({'event': 'migration_started', 'action': args.action}), flush=True)
        result = execute(args)
        print(json.dumps({'event': 'migration_succeeded', 'action': args.action, 'result': result}), flush=True)
    except (ValueError, RuntimeError, KeyError, OSError) as error:
        print(json.dumps({'event': 'migration_failed', 'action': args.action, 'error': str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
