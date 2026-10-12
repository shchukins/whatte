"""Fail-closed NAS/backup gates without private data or external infrastructure."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


gate = module('nas_backup_gate')
backup = module('postgres_backup')

MOUNT = '/mnt/whatte-backups'
SOURCE = '192.0.2.10:/Volume1/whatte-backups'
GOOD = '72 30 0:50 / /mnt/whatte-backups rw,relatime - nfs4 192.0.2.10:/Volume1/whatte-backups rw,vers=4.2,proto=tcp'


def test_actual_nfs_mount_required():
    assert gate.verify_mount(GOOD, MOUNT, SOURCE)['nfs_version'] == '4.2'


@pytest.mark.parametrize('mountinfo', ['',
    GOOD.replace('nfs4', 'autofs'), GOOD.replace(SOURCE, '192.0.2.11:/other'),
    GOOD.replace('vers=4.2', 'vers=4.1'), GOOD.replace('rw,relatime', 'ro,relatime'), GOOD + '\n' + GOOD])
def test_local_directory_wrong_export_and_unavailable_nas_block(mountinfo):
    with pytest.raises(ValueError):
        gate.verify_mount(mountinfo, MOUNT, SOURCE)


def test_unrestricted_shell_is_rejected(monkeypatch):
    class Stat:
        st_uid = 0
        st_mode = 0o644
    monkeypatch.setattr(Path, 'stat', lambda *args, **kwargs: Stat())
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: '{}')
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'rm -rf /')
    assert gate.main() == 1


def receipt(tmp_path):
    path = tmp_path / 'proof.json'
    timestamp = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps({'sha256': 'a' * 64, 'remote_archive': MOUNT + '/postgres/whatte-test.dump.age',
        'restore_verified': True, 'verified_at': timestamp, 'created_at': timestamp,
        'receiver_guard_active': True, 'off_host_encrypted': True}))
    return path


def test_nas_failure_blocks_even_with_valid_cached_restore(tmp_path, monkeypatch):
    path = receipt(tmp_path)
    monkeypatch.setattr(backup, 'nas_probe', lambda config: (_ for _ in ()).throw(RuntimeError('offline')))
    with pytest.raises(RuntimeError, match='offline'):
        backup.verify({'remote_directory': MOUNT + '/postgres'}, path)


def test_archive_corruption_blocks(tmp_path, monkeypatch):
    path = receipt(tmp_path)
    monkeypatch.setattr(backup, 'nas_probe', lambda config: {})
    monkeypatch.setattr(backup, 'sftp', lambda config, command: None)
    monkeypatch.setattr(backup, 'sha256', lambda path: 'b' * 64)
    with pytest.raises(ValueError, match='checksum mismatch'):
        backup.verify({'local_directory': str(tmp_path), 'remote_directory': MOUNT + '/postgres'}, path)


@pytest.mark.parametrize('field,value', [('restore_verified',False), ('receiver_guard_active',False),
    ('verified_at','2000-01-01T00:00:00+00:00'), ('remote_archive','/another/whatte-test.dump.age')])
def test_incomplete_manual_stale_or_outside_archive_is_rejected(tmp_path, field, value):
    path = receipt(tmp_path)
    data = json.loads(path.read_text()); data[field] = value; path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        backup.verify({'remote_directory': MOUNT + '/postgres'}, path)


@pytest.mark.parametrize('path', ['bad\nfile', 'bad"file', 'bad\\file'])
def test_sftp_path_cannot_inject_batch_commands(path):
    with pytest.raises(ValueError):
        backup.quote(path)


def test_restore_rejects_unexpected_members_before_docker(tmp_path):
    import io
    import tarfile
    restore = module('verify_postgres_restore')
    archive = tmp_path / 'bad.tar'
    with tarfile.open(archive, 'w') as tar:
        member = tarfile.TarInfo('../escape'); member.size = 1
        tar.addfile(member, io.BytesIO(b'x'))
    with pytest.raises(ValueError, match='Unexpected backup bundle members'):
        restore.restore(archive, ROOT, tmp_path / 'proof.json')
    assert not (tmp_path / 'proof.json').exists()


def test_recent_restore_does_not_make_old_archive_fresh(tmp_path):
    path = receipt(tmp_path)
    value = json.loads(path.read_text()); value['created_at'] = '2000-01-01T00:00:00+00:00'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='archive is stale'):
        backup.verify({'remote_directory': MOUNT + '/postgres'}, path)
