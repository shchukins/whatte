#!/usr/bin/env bash
# Explicitly approved operator installation only. No backup files are touched.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
    echo 'Run the reviewed installer with sudo after explicit approval.' >&2
    exit 1
fi
stage=${1:?staging directory required}
config=${2:?site NAS configuration required}
gate=/usr/local/libexec/whatte-backup-nfs-gate
installed_config=/etc/whatte-backup/nas-gate.json
ssh_config=/etc/ssh/sshd_config.d/00-whatte-backup-gate.conf
for file in "$gate" "$installed_config" "$ssh_config"; do
    [[ ! -e "$file" ]] || { echo "Refusing to overwrite $file" >&2; exit 1; }
done
# Review the original effective account rules before changing them.
/usr/sbin/sshd -t
original=$(/usr/sbin/sshd -T -C user=whatte-backup,host=localhost,addr=127.0.0.1)
printf '%s\n' "$original" | sed -n '/^forcecommand /p; /^chrootdirectory /p'
chroot=$(printf '%s\n' "$original" | sed -n 's/^chrootdirectory //p')
[[ "$chroot" == none ]] || { echo 'Existing chroot requires a separate runtime/path review.' >&2; exit 1; }
old_shell=$(getent passwd whatte-backup | cut -d: -f7)
getent passwd whatte-backup
created=0
shell_changed=0
recover() {
    status=$?
    if [[ $status -ne 0 && $created -eq 1 ]]; then
        if [[ $shell_changed -eq 1 ]]; then usermod --shell "$old_shell" whatte-backup; fi
        # These destinations were proved absent before this invocation.
        rm -f -- "$ssh_config" "$installed_config" "$gate"
        /usr/sbin/sshd -t && systemctl reload ssh
    fi
    exit "$status"
}
trap recover EXIT
python3 - "$config" <<'PY'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
if value['mountpoint']!='/mnt/whatte-backups' or value['backup_directory']!='/mnt/whatte-backups/postgres':
    raise SystemExit('Unexpected NAS mount/directory')
if value['source']=='NAS_IP:/Volume1/whatte-backups':
    raise SystemExit('Populate the reviewed actual NFS export')
PY
mkdir -p /usr/local/libexec /etc/whatte-backup
created=1
install -o root -g root -m 0755 "$stage/nas_backup_gate.py" "$gate"
install -o root -g root -m 0644 "$config" "$installed_config"
install -o root -g root -m 0644 "$stage/00-whatte-backup-gate.conf" "$ssh_config"
/usr/sbin/sshd -t
actual=$(/usr/sbin/sshd -T -C user=whatte-backup,host=localhost,addr=127.0.0.1 | sed -n 's/^forcecommand //p')
[[ "$actual" == "$gate" ]] || { echo 'Effective ForceCommand mismatch; do not activate.' >&2; exit 1; }
# The old nologin shell cannot execute a forced external command. Replace it
# with this same restricted gate, never with a general shell such as /bin/bash.
usermod --shell "$gate" whatte-backup
shell_changed=1
systemctl reload ssh
printf 'Restricted NAS probe and SFTP gate installed. Verify from the VPS before activating backups.\n'
