#!/usr/bin/env python3
"""Verify a decrypted backup bundle in a new network-isolated PostgreSQL container."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import uuid

IMAGE = 'mirror.gcr.io/pgvector/pgvector@sha256:41599f76505f3a9450355e34c83a4fd215a8099ea66fcb8b38049b15da155ee7'


def run(command, *, input=None):
    value = subprocess.run(command, input=input, text=True, capture_output=True, timeout=120)
    if value.returncode:
        raise RuntimeError('Isolated restore command failed at ' + Path(command[0]).name + '/' + str(command[1]) + '; private output suppressed')
    return value.stdout.strip()


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            sha.update(chunk)
    return sha.hexdigest()


def restore(bundle, repo, evidence):
    started = time.monotonic()
    container = 'whatte-restore-test-' + uuid.uuid4().hex[:16]
    container_attempted = False
    try:
        with tempfile.TemporaryDirectory(prefix='whatte-restore-') as tmp:
            root = Path(tmp)
            with tarfile.open(bundle) as archive:
                names = [member.name for member in archive.getmembers()]
                if sorted(names) != ['database.dump', 'manifest.json', 'roles.sql']:
                    raise ValueError('Unexpected backup bundle members')
                if not all(member.isfile() for member in archive.getmembers()):
                    raise ValueError('Backup bundle may only contain regular files')
                archive.extractall(root, filter='data')
            manifest = json.loads((root / 'manifest.json').read_text())
            if manifest['format'] != 'whatte_postgres_backup_v1' or manifest['postgres_major'] != 16:
                raise ValueError('Unsupported backup format or PostgreSQL major version')
            for file, field in [('database.dump', 'database_dump_sha256'), ('roles.sql', 'roles_sha256')]:
                if digest(root / file) != manifest[field]:
                    raise ValueError('Decrypted backup member checksum mismatch')
            owner = manifest['owner']
            if not owner.replace('_', '').isalnum():
                raise ValueError('Unsupported bootstrap owner identifier')
            container_attempted = True
            run(['docker', 'run', '-d', '--name', container, '--network', 'none', '--memory', '512m',
                 '-e', 'POSTGRES_USER=' + owner, '-e', 'POSTGRES_DB=postgres',
                 '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', IMAGE])
            for _ in range(30):
                ready = subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', owner],
                                       capture_output=True)
                if ready.returncode == 0:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Disposable PostgreSQL did not become ready')
            psql = ['docker', 'exec', '-i', container, 'psql', '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-U', owner]
            # Bootstrap with the original owner so template plpgsql and restored
            # extensions retain their original owner without system-catalog edits.
            roles_sql = (root / 'roles.sql').read_text()
            create_owner = ['CREATE ROLE ' + owner + ';', 'CREATE ROLE "' + owner + '";']
            for statement in create_owner:
                roles_sql = roles_sql.replace(statement, '-- Owner already provisioned by isolated initdb.')
            run(psql + ['-d', 'postgres'], input=roles_sql)
            # Identifiers originate from a decrypted, hash-checked backup. Quote
            # them as identifiers; do not interpolate them as shell command text.
            quoted_owner = '"' + owner.replace('"', '""') + '"'
            run(psql + ['-d', 'postgres'], input='CREATE DATABASE restored OWNER ' + quoted_owner + ';')
            run(['docker', 'cp', str(root / 'database.dump'), container + ':/tmp/database.dump'])
            run(['docker', 'exec', container, 'pg_restore', '-U', owner, '-d', 'restored',
                 '--exit-on-error', '--single-transaction', '/tmp/database.dump'])
            source_counts = manifest['snapshot_table_counts']
            tables = json.loads(run(psql + ['-d', 'restored'], input="SELECT json_agg(format('%I.%I',schemaname,tablename) ORDER BY schemaname,tablename) FROM pg_tables WHERE schemaname NOT LIKE 'pg_%' AND schemaname <> 'information_schema';"))
            if sorted(tables) != sorted(source_counts):
                raise ValueError('Restored table inventory differs')
            parts = ["SELECT '" + table.replace("'", "''") + "' name, count(*) rows FROM " + table for table in tables]
            counts = json.loads(run(psql + ['-d', 'restored'], input='SELECT json_object_agg(name,rows) FROM (' + ' UNION ALL '.join(parts) + ') t;'))
            if counts != source_counts:
                raise ValueError('Restored snapshot table counts differ')
            catalog = json.loads(run(psql + ['-d', 'restored'], input=(repo / 'migrations/verification/catalog.sql').read_text()))
            expected = json.loads((repo / 'migrations/verification/expected_catalog.json').read_text())
            if catalog != expected:
                keys = sorted(k for k in catalog.keys() | expected.keys() if catalog.get(k) != expected.get(k))
                raise ValueError('Restored catalog differs: ' + ', '.join(keys[:20]))
            checks = json.loads(run(psql + ['-d', 'restored'], input=(repo / 'migrations/verification/backfill_checks.sql').read_text()))
            if any(checks.values()):
                raise ValueError('Restored backfill postconditions differ')
            # A real application read, with synthetic settings and no outbound
            # network. Emit only success; athlete rows never enter operator logs.
            functional = """from datetime import date
from backend.db import get_conn
from backend.today.history_service import get_diary_data
with get_conn() as conn:
    assert conn.execute('SELECT 1').fetchone()[0] == 1
    row = conn.execute('SELECT user_id, date FROM readiness_daily ORDER BY date DESC LIMIT 1').fetchone()
if row:
    diary = get_diary_data(row[0], row[1])
    assert diary.activity_section.status == "ok"
    assert diary.history_section.status == "ok"
    assert diary.profile_pending_section.status == "ok"
print('functional_read_ok')
"""
            result = run(['docker', 'run', '--rm', '--network', 'container:' + container,
                          '-v', str(repo / 'backend') + ':/app:ro', '-e', 'PYTHONPATH=/app',
                          '-e', 'DATABASE_URL=postgresql://' + owner + '@127.0.0.1:5432/restored',
                          '-e', 'STRAVA_VERIFY_TOKEN=test', '-e', 'STRAVA_CLIENT_ID=12345',
                          '-e', 'STRAVA_CLIENT_SECRET=test', '-e', 'STRAVA_REDIRECT_URI=https://example.com/strava/callback',
                          'human-engine-backend', 'python', '-c', functional])
            if 'functional_read_ok' not in result:
                raise ValueError('Functional app read did not succeed')
            proof = {'restore_verified': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
                     'bundle_sha256': digest(bundle), 'source_sha': manifest['source_sha'],
                     'all_snapshot_table_counts_match': True, 'catalog_elements': len(catalog),
                     'functional_read': True, 'duration_seconds': round(time.monotonic() - started, 2),
                     'private_restore_key_on_vps': False}
            with evidence.open('x') as f:
                os.chmod(evidence, 0o600)
                json.dump(proof, f, indent=2)
            return proof
    finally:
        if container_attempted:
            subprocess.run(['docker', 'rm', '-f', '-v', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(restore(args.bundle, args.repo, args.evidence)))
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'restore_verified': False, 'reason': str(error)}))
        raise SystemExit(1)
