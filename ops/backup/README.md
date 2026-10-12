# WHATTE PostgreSQL backup and NAS gate

This is an explicit operator installation, not an automatic deployment activation.
Do not install SSH rules, change account shells or enable systemd units without
separate authorization. Never overwrite existing backup files or directories.

## Prepared receiving-side change

The `whatte-backup` account currently has `/usr/sbin/nologin`. External forced
commands cannot execute through that shell. The reviewed installer:

1. Records the existing effective SSH rules and rejects existing destination files.
2. Installs the root-owned [NAS gate](../../scripts/nas_backup_gate.py) and site
   config. It checks a real writable NFSv4.2 mount with the expected export after
   triggering automount through a bounded lookup; a mere directory is rejected.
3. Adds [a dedicated SSH Match rule](00-whatte-backup-gate.conf) for `whatte-backup`.
   The only allowed requests are the exact `whatte-backup-probe-v1` command and
   SFTP. Forwarding, PTY and arbitrary command execution remain unavailable.
4. Validates SSH configuration and the effective ForceCommand before activation.
5. Changes that account's shell to the same root-owned restricted gate, not a
   general shell, then reloads SSH. Other SSH accounts are outside this change.

Run from an already-open operator session, keeping it open while verifying the
new connection. Backup clients explicitly select the permitted fixed external
SFTP server (`sftp -s /usr/lib/openssh/sftp-server`), which works through this
restricted shell; subsystem-mode SFTP is not used. The installer requires sudo
on the home server:

```sh
sudo bash /home/shch/whatte-187-backup-setup/install-nas-gate.sh \
  /home/shch/whatte-187-backup-setup \
  /home/shch/whatte-187-backup-setup/nas-gate.json
```

Those staging files are prepared; no root installation has occurred. Review the
actual site export in the staging JSON before approval. After installation verify
from the VPS with the dedicated key: the fixed probe returns the correct guard,
export and protocol; SFTP works; an arbitrary command fails. Keep operator SSH
out of the recurring backup process. If the existing account is chrooted, abort
and review path/runtime availability before installing an external gate.

Recovery of this configuration is an operator action: restore the recorded old
shell (`/usr/sbin/nologin`) and remove only this installation's Match include, then
validate/reload SSH. Never touch NAS data to recover an SSH configuration change.

## Backup format and encryption

[`postgres_backup.py`](../../scripts/postgres_backup.py) creates a read-only
repeatable-read snapshot. The custom-format `database.dump` and exact per-table
counts come from the same exported snapshot. Global role definitions are saved
without password hashes. A versioned bundle contains only `database.dump`,
`roles.sql`, and `manifest.json`; the manifest includes member hashes, source SHA
and private snapshot counts. The tar bundle is encrypted with age into one new
unique `whatte-<UTC timestamp>-<128-bit random id>.dump.age` file.

Thus a `.dump.age` file decrypts into a **tar bundle**, not directly into pg_restore
input. Verify member names/hashes, then pass its `database.dump` to pg_restore.
Only `.dump.age` ciphertext is transferred to NAS. Staging directories are 0700;
private config and files are 0600. Raw staging is deleted in finally; existing
archives are never overwritten or pruned. Retain all copies until a separately
approved retention process is available; capacity/exhaustion failures block backup.

age 1.3.2 binaries were selected from the
[official release](https://github.com/FiloSottile/age/releases/tag/v1.3.2) with
published archive SHA-256 verification. The recovery private key is generated
and stored only on the operator's Mac, outside Git. Only its public recipient
is installed on VPS. Neither key is tracked in Git. Do not print the private key
or copy it to VPS/NAS. Keep a deliberate separate recovery-key copy under the
operator's physical/control policy; the NAS archive alone cannot recover the DB.

A backup succeeds only after the restricted receiver probe, dump/encryption,
SFTP upload, round-trip download/checksum and second receiver probe succeed.
Manual NFS evidence is supported only for the first operator rehearsal and creates
`receiver_guard_active=false`; it cannot authorize production migrations.

## Restore drill and migration gating

Download the NAS ciphertext, verify its hash and decrypt on the Mac with the local
private key. Transfer only the temporary decrypted bundle to a protected VPS test
staging directory. [`verify_postgres_restore.py`](../../scripts/verify_postgres_restore.py)
uses a new named PostgreSQL 16 + pgvector container with no network/host ports,
restores role definitions, schema and data, verifies every snapshot table count,
822 baseline catalog elements, historical backfill conditions and a real Diary
application read. The original owner initializes the disposable cluster so
plpgsql/pgvector ownership is preserved without editing system catalogs. Test
containers/volumes and new plaintext files must be removed after verification;
production PostgreSQL and existing backup files remain untouched.

The first actual NAS backup completed this full cycle on 2026-10-12. Snapshot
counts/catalog and application reads passed; restore took 7.48 seconds. NAS
ciphertext was fetched back and age-decrypted on the Mac. Private data/counts and
key material are absent from Git and issue logs. The receiver gate and timer
still require explicit infrastructure approval and installation.

`migrate.py` now binds approval to the backup config/proof SHA and archive hash,
then calls `postgres_backup.py verify` to recheck **live NFS availability and the
actual NAS archive checksum immediately before SQL writes**. Cached boolean
attestations cannot bypass an unavailable NAS or corrupt archive. A restore proof
must identify this archive and be at most 24h old. All pending production schema
writes, including baseline, require these checks. Approval remains a distinct gate.

## Daily backup service (not yet enabled)

The proposed [timer](whatte-postgres-backup.timer) runs daily at 02:00 UTC
(05:00 Europe/Moscow), including catch-up after downtime. It runs as the VPS
operator and transfers only through `whatte-backup`; no recurring operator SSH.
The [service](whatte-postgres-backup.service) fails nonzero and a failure unit emits
an error event into the system journal. Operator monitoring must consume/check
that status; no external email/Telegram notification is installed by this task.
Daily ciphertext integrity checks do not claim a new restore/decrypt verification;
the private key is available only on Mac. Before a schema change, create a fresh
backup and perform the separately reviewed full restore drill for its exact archive.

After receiver activation and a successful verified restore receipt, the separately
approved VPS installer refuses to replace existing units/config:

```sh
sudo bash /srv/human-engine/ops/backup/install-backup-timer.sh \
  /srv/human-engine /protected/backup.json /protected/restored-receipt.json
```

Site configuration is private and follows [backup.example.json](backup.example.json).
Do not include recipients or private identities in Git. The routine backup config
is `/home/sergey/.config/whatte-backup/backup.json`; it remains outside the checkout.
Check `systemctl list-timers whatte-postgres-backup.timer`, `systemctl status
whatte-postgres-backup.service` and its journal. Automatic production deployment
and automatic migration activation remain disabled.
