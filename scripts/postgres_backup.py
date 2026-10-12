#!/usr/bin/env python3
"""Create immutable age-encrypted PostgreSQL backup bundles; never prune old files."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid

GUARD_ID = 'whatte_nfs_sftp_v1'


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def run(command, *, input=None, stdout=None, timeout=300):
    result = subprocess.run(command, input=input, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE,
                            text=stdout is None, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{Path(command[0]).name} failed (exit {result.returncode}); private data was suppressed')
    return result.stdout


def ssh_options(config):
    return ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2', '-i', config['ssh_key']]


def nas_probe(config):
    value = json.loads(run(['ssh', *ssh_options(config), config['sftp_target'], 'whatte-backup-probe-v1'], timeout=45))
    if (value.get('guard') != GUARD_ID or value.get('source') != config['nas_source']
            or value.get('mountpoint') != config['nas_mountpoint'] or value.get('nfs_version') != '4.2'
            or value.get('backup_directory') != config['remote_directory']):
        raise ValueError('Receiver NAS proof does not match the configured mount')
    return value


def sftp(config, commands):
    # Batch mode stops on any failed command; never prefix a command with '-'.
    return run(['sftp', '-s', '/usr/lib/openssh/sftp-server', *ssh_options(config),
                '-b', '-', config['sftp_target']], input=commands, timeout=180)


def quote(path):
    value = str(path)
    if any(c in value for c in ('\n', '\r', '"', '\\')):
        raise ValueError('Unsafe SFTP path')
    return '"' + value + '"'


def exclusive_json(path, value):
    with Path(path).open('x') as f:
        os.chmod(path, 0o600)
        json.dump(value, f, indent=2)
        f.write('\n')


def create(config, manual_evidence=None):
    # Manual mount evidence is only for an operator's first full-cycle rehearsal;
    # migration receipts cannot use it to authorize automated production writes.
    if manual_evidence:
        proof = json.loads(Path(manual_evidence).read_text())
        if proof.get('guard') != GUARD_ID or proof.get('source') != config['nas_source']:
            raise ValueError('Manual NAS evidence mismatch')
        if (datetime.now(timezone.utc) - datetime.fromisoformat(proof['checked_at'])).total_seconds() > 300:
            raise ValueError('Manual NAS evidence is stale')
    else:
        proof = nas_probe(config)
    directory = Path(config['local_directory'])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError('Backup staging directory must be owned by the operator with mode 0700')
    name = 'whatte-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    work = directory / name
    work.mkdir(mode=0o700)  # Unique directory; existing backups are never overwritten.
    dump = work / 'database.dump'
    roles = work / 'roles.sql'
    container = config['postgres_container']
    user = config['postgres_user']
    database = config['postgres_database']
    psql = ['docker', 'exec', '-i', container, 'psql', '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-U', user, '-d', database]
    exporter = subprocess.Popen(psql, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        exporter.stdin.write('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n')
        exporter.stdin.flush()
        snapshot = exporter.stdout.readline().strip()
        if snapshot == 'BEGIN':
            snapshot = exporter.stdout.readline().strip()
        if not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', snapshot):
            raise RuntimeError('Could not obtain a consistent PostgreSQL snapshot')
        tables = json.loads(run(psql, input="SELECT json_agg(format('%I.%I',schemaname,tablename) ORDER BY schemaname,tablename) FROM pg_tables WHERE schemaname NOT LIKE 'pg_%' AND schemaname <> 'information_schema';"))
        parts = ["SELECT '" + table.replace("'", "''") + "' AS name, count(*) AS rows FROM " + table for table in tables]
        exporter.stdin.write('SELECT json_object_agg(name,rows) FROM (' + ' UNION ALL '.join(parts) + ') t;\n')
        exporter.stdin.flush()
        counts = json.loads(exporter.stdout.readline())
        with dump.open('xb') as f:
            os.chmod(dump, 0o600)
            run(['docker', 'exec', container, 'pg_dump', '-U', user, '-d', database, '--format=custom', '--snapshot=' + snapshot], stdout=f)
        exporter.stdin.write('ROLLBACK;\n'); exporter.stdin.flush()
        exporter.stdin.close()
        exporter.wait(timeout=30)
        with roles.open('xb') as f:
            os.chmod(roles, 0o600)
            run(['docker', 'exec', container, 'pg_dumpall', '-U', user, '--globals-only', '--no-role-passwords'], stdout=f)
        source_sha = run(['git', '-C', config['repo_directory'], 'rev-parse', 'HEAD']).strip()
        manifest = {'format': 'whatte_postgres_backup_v1', 'created_at': datetime.now(timezone.utc).isoformat(),
                    'source_sha': source_sha, 'database': database, 'owner': user,
                    'postgres_major': 16, 'database_dump_sha256': sha256(dump), 'roles_sha256': sha256(roles),
                    'snapshot_table_counts': counts}
        exclusive_json(work / 'manifest.json', manifest)
        bundle = work / 'backup.tar'
        with tarfile.open(bundle, 'x') as archive:
            for member in ('database.dump', 'roles.sql', 'manifest.json'):
                archive.add(work / member, arcname=member, recursive=False)
        os.chmod(bundle, 0o600)
        encrypted = directory / (name + '.dump.age')
        # age --output itself can overwrite: reserve/check an exclusive destination
        # and stream ciphertext to the exclusive descriptor instead.
        with encrypted.open('xb') as f:
            os.chmod(encrypted, 0o600)
            run([config['age_binary'], '-R', config['recipient_file'], str(bundle)], stdout=f)
        remote = config['remote_directory'] + '/' + encrypted.name
        # Unique random filename plus explicit nonexistence check. SFTP account is
        # restricted; concurrent backups use different 128-bit names.
        listing = sftp(config, 'ls -1 ' + quote(config['remote_directory']) + '\n')
        if encrypted.name in listing.splitlines():
            raise ValueError('Remote backup name already exists')
        sftp(config, 'put ' + quote(encrypted) + ' ' + quote(remote) + '\n')
        returned = work / 'roundtrip.dump.age'
        sftp(config, 'get ' + quote(remote) + ' ' + quote(returned) + '\n')
        if sha256(returned) != sha256(encrypted):
            raise ValueError('Transferred archive checksum mismatch')
        if not manual_evidence:
            nas_probe(config)
        result = {'archive': str(encrypted), 'remote_archive': remote, 'sha256': sha256(encrypted),
                  'created_at': manifest['created_at'], 'source_sha': source_sha,
                  'receiver_guard_active': not bool(manual_evidence), 'restore_verified': False,
                  'off_host_encrypted': True, 'nas_proof': proof}
        exclusive_json(directory / (name + '.receipt.json'), result)
        return result
    finally:
        if exporter.poll() is None:
            exporter.kill()
            exporter.wait(timeout=10)
        if exporter.stdout:
            exporter.stdout.close()
        if exporter.stderr:
            exporter.stderr.close()
        # Only this invocation's new plaintext staging files are removed.
        shutil.rmtree(work)


def verify(config, receipt):
    value = json.loads(Path(receipt).read_text())
    if value.get('restore_verified') is not True:
        raise ValueError('An explicit restore proof for this archive is required')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(value['verified_at'])).total_seconds()
    if not re.fullmatch(r'[0-9a-f]{64}', value.get('sha256', '')):
        raise ValueError('Invalid backup archive checksum')
    if not 0 <= age <= 86400:
        raise ValueError('Restore proof is stale')
    remote = Path(value['remote_archive'])
    if str(remote.parent) != config['remote_directory'] or not re.fullmatch(r'whatte-[a-zA-Z0-9-]+\.dump\.age', remote.name):
        raise ValueError('Backup receipt points outside the configured archive directory')
    if value.get('receiver_guard_active') is not True or value.get('off_host_encrypted') is not True:
        raise ValueError('Migration requires the restricted receiver NAS gate')
    nas_probe(config)
    with tempfile.TemporaryDirectory(prefix='whatte-backup-check-', dir=config['local_directory']) as tmp:
        path = Path(tmp) / 'verified.dump.age'
        sftp(config, 'get ' + quote(value['remote_archive']) + ' ' + quote(path) + '\n')
        if sha256(path) != value['sha256']:
            raise ValueError('Off-host archive checksum mismatch')
    return {'nas_available': True, 'archive_integrity': True, 'sha256': value['sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('--config', required=True)
    parser.add_argument('--receipt')
    parser.add_argument('--manual-nfs-evidence', help='Initial operator rehearsal only; not a migration approval')
    args = parser.parse_args()
    try:
        path = Path(args.config)
        if path.stat().st_uid not in {0, os.getuid()} or path.stat().st_mode & 0o077:
            raise ValueError('Backup configuration must be protected (0600)')
        config = json.loads(path.read_text())
        if not re.fullmatch(r'whatte-backup@[a-zA-Z0-9.-]+', config['sftp_target']):
            raise ValueError('Automatic backup must use the dedicated whatte-backup account')
        result = create(config, args.manual_nfs_evidence) if args.action == 'create' else verify(config, args.receipt)
        print(json.dumps({'event': 'backup_succeeded', 'action': args.action, 'result': result}))
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired):
        print(json.dumps({'event': 'backup_failed', 'action': args.action}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
