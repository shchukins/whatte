#!/usr/bin/python3
"""Root-owned forced SSH command for the backup account; no operator shell."""
import json
import os
from pathlib import Path
import subprocess
import sys

CONFIG = Path('/etc/whatte-backup/nas-gate.json')
PROBE_COMMAND = 'whatte-backup-probe-v1'
GUARD_ID = 'whatte_nfs_sftp_v1'


def decode_mount(value):
    for escaped, plain in [('\\040', ' '), ('\\011', '\t'), ('\\012', '\n'), ('\\134', '\\')]:
        value = value.replace(escaped, plain)
    return value


def verify_mount(mountinfo, mountpoint, source):
    candidates = []
    for line in mountinfo.splitlines():
        before, after = line.split(' - ', 1)
        fields, fs = before.split(), after.split()
        if decode_mount(fields[4]) == mountpoint and fs[0] in {'nfs', 'nfs4'}:
            candidates.append((decode_mount(fs[1]), fields[5].split(','), fs[2].split(',')))
    if len(candidates) != 1:
        raise ValueError('Actual NFS mount is absent or ambiguous')
    actual_source, options, super_options = candidates[0]
    if actual_source != source or 'rw' not in options or 'vers=4.2' not in super_options:
        raise ValueError('Unexpected NFS source, protocol or write mode')
    return {'guard': GUARD_ID, 'mountpoint': mountpoint, 'source': source, 'nfs_version': '4.2'}


def probe(config):
    mountpoint = config['mountpoint']
    directory = config['backup_directory']
    if not Path(directory).is_relative_to(Path(mountpoint)) or directory == mountpoint:
        raise ValueError('Backup directory must be under the configured mount')
    # Trigger systemd automount without creating/changing a directory. The child
    # may wait in the NFS kernel path; the parent must fail closed on timeout.
    lookup = subprocess.Popen(['stat', '--', directory], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if lookup.wait(timeout=15) != 0:
            raise ValueError('Backup directory is inaccessible')
    except subprocess.TimeoutExpired:
        lookup.kill()
        raise ValueError('NAS lookup timed out')
    result = verify_mount(Path('/proc/self/mountinfo').read_text(), mountpoint, config['source'])
    result['backup_directory'] = directory
    return result


def main():
    try:
        st = CONFIG.stat()
        if st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError('NAS gate configuration must be root-owned and immutable to backup users')
        config = json.loads(CONFIG.read_text())
        command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
        if command not in {PROBE_COMMAND, 'internal-sftp', '/usr/lib/openssh/sftp-server'}:
            raise ValueError('Only the fixed NAS probe and SFTP are permitted')
        result = probe(config)
        if command == PROBE_COMMAND:
            print(json.dumps(result))
            return 0
        os.execv('/usr/lib/openssh/sftp-server', ['sftp-server', '-d', config['backup_directory'], '-u', '0077'])
    except (ValueError, OSError, KeyError):
        print('WHATTE backup gate rejected the connection', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
