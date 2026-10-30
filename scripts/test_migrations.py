#!/usr/bin/env python3
"""Destructive failure rehearsals, restricted to a disposable PostgreSQL cluster."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

from migrate import ROOT, FLYWAY_IMAGE, canonical_hash, digest, psql, target_environment


class MigrationLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('MIGRATION_ENVIRONMENT') != 'ci' or os.environ.get('MIGRATION_TEST_DISPOSABLE') != 'yes':
            raise RuntimeError('Use a disposable cluster; set MIGRATION_ENVIRONMENT=ci and MIGRATION_TEST_DISPOSABLE=yes')
        _, cls.admin = target_environment()
        # V1 creates global NOLOGIN permission groups; never run against production.

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / 'migrations', self.root / 'migrations')
        # Safety/adoption rehearsals intentionally exercise the immutable V1
        # baseline; application migrations are applied in the CI database job.
        manifest_path = self.root / 'migrations/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for item in manifest['migrations'][1:]:
            (self.root / 'migrations/sql' / item['file']).unlink()
        manifest['migrations'] = manifest['migrations'][:1]
        manifest_path.write_text(json.dumps(manifest))
        (self.root / 'scripts').mkdir()
        shutil.copy(ROOT / 'scripts/migrate.py', self.root / 'scripts/migrate.py')
        # Synthetic NAS adapter exists only in the disposable test checkout.
        (self.root / 'scripts/postgres_backup.py').write_text(
            "import json,sys; from pathlib import Path; p=Path(sys.argv[sys.argv.index('--receipt')+1]); "
            "print(json.dumps({'event':'backup_succeeded','result':{'sha256':json.loads(p.read_text())['sha256']}}))")
        self.db = 'migration_test_' + uuid.uuid4().hex[:12]
        psql(self.admin, f'CREATE DATABASE {self.db};')
        self.env = os.environ.copy()
        self.env['FLYWAY_URL'] = f'jdbc:postgresql://{self.admin.hostname}:{self.admin.port or 5432}/{self.db}'
        self.env['MIGRATION_ENVIRONMENT'] = 'ci'
        self.env['MIGRATION_RUN_ID'] = self.db
        self.target = __import__('urllib.parse', fromlist=['urlparse']).urlparse(self.env['FLYWAY_URL'][5:])

    def tearDown(self):
        psql(self.admin, f'DROP DATABASE {self.db} WITH (FORCE);')
        self.tmp.cleanup()

    def command(self, action, *, good=True, extra=()):
        result = subprocess.run(['python3', str(self.root / 'scripts/migrate.py'), action, *extra],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, good, result.stdout + result.stderr)
        if good:
            return json.loads(result.stdout.splitlines()[-1])['result']
        return result

    def sql(self, sql):
        return psql(self.target, sql).strip()

    def add_migration(self, sql, risk='compatible'):
        name = 'V2__test.sql'
        (self.root / 'migrations/sql' / name).write_text(sql)
        path = self.root / 'migrations/manifest.json'
        manifest = json.loads(path.read_text())
        manifest['migrations'].append({'file': name, 'sha256': digest(self.root / 'migrations/sql' / name),
                                      'risk': risk, 'transactional': True, 'old_app_compatible': True})
        path.write_text(json.dumps(manifest))

    def receipt(self, action):
        catalog = json.loads(self.sql((self.root / 'migrations/verification/catalog.sql').read_text()))
        receipt = {'action': action, 'authorized_by': 'synthetic-ci-fixture', 'authorization_reference': 'test-only',
                   'target': self.env['FLYWAY_URL'], 'manifest_sha256': digest(self.root / 'migrations/manifest.json'),
                   'catalog_hash': canonical_hash(catalog), 'backup': {'restore_verified': True,
                       'off_host_encrypted': True, 'sha256': 'a' * 64, 'reference': 'synthetic-test-only',
                       'regular_backup_process': 'synthetic-test-only', 'verified_at': datetime.now(timezone.utc).isoformat()}}
        config = self.root / 'backup-config.json'; config.write_text('{}')
        restore_proof = self.root / 'restore-proof.json'
        restore_proof.write_text(json.dumps({'sha256': receipt['backup']['sha256'], 'verified_at': receipt['backup']['verified_at']}))
        receipt['backup'].update(config_path=str(config), config_sha256=digest(config),
                                 receipt_path=str(restore_proof), receipt_sha256=digest(restore_proof))
        path = self.root / 'approval.json'
        path.write_text(json.dumps(receipt))
        return path, receipt

    def test_fresh_repeat_and_catalog(self):
        self.assertEqual(self.command('migrate')['migrationsExecuted'], 1)
        self.command('verify-baseline')
        before = self.sql('select row_to_json(h) from flyway_schema_history h;')
        self.assertEqual(self.command('migrate')['migrationsExecuted'], 0)
        self.assertEqual(before, self.sql('select row_to_json(h) from flyway_schema_history h;'))
        self.command('validate')
        # Old application writes remain legal against the new baseline.
        self.sql("insert into notification_log(user_id,notification_type,notification_date) values ('test','daily_readiness',current_date);")
        self.sql("insert into strava_webhook_event(owner_id,object_type,object_id,aspect_type,event_time,payload,dedupe_key) values (1,'activity',1,'create',now(),'{}','test') on conflict(dedupe_key) do nothing;")

    def test_checksum_changes_block_validation_and_migrate(self):
        self.command('migrate')
        path = self.root / 'migrations/sql/V1__baseline.sql'
        path.write_text(path.read_text() + '\n-- illicit applied-history edit\n')
        manifest_path = self.root / 'migrations/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['migrations'][0]['sha256'] = digest(path)
        manifest_path.write_text(json.dumps(manifest))
        self.command('validate', good=False)
        self.command('migrate', good=False)

    def test_failed_transaction_rolls_back_and_blocks_repeat(self):
        self.command('migrate')
        self.add_migration('CREATE TABLE failed_probe(id integer); SELECT no_such_column;')
        self.command('migrate', good=False)
        self.assertEqual(self.sql("select to_regclass('failed_probe') is null;"), 't')
        self.assertEqual(self.sql("select count(*) from flyway_schema_history where version='2';"), '0')
        self.command('migrate', good=False)

    def test_concurrent_runners_are_serialized(self):
        self.command('migrate')
        self.add_migration('SELECT pg_sleep(15); CREATE TABLE concurrent_probe(id integer);')
        first = subprocess.Popen(['python3', str(self.root / 'scripts/migrate.py'), 'migrate'],
                                 env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: first.communicate(timeout=60))
        self.wait_for_sleep(first)
        second = self.command('migrate', good=False)
        self.assertIn('migration_failed', second.stderr)
        out, err = first.communicate(timeout=60)
        self.assertEqual(first.returncode, 0, out + err)
        self.assertEqual(self.command('migrate')['migrationsExecuted'], 0)
        self.assertEqual(self.sql("select count(*) from flyway_schema_history where version='2' and success;"), '1')

    def wait_for_sleep(self, process):
        for _ in range(30):
            if process.poll() is not None:
                out, err = process.communicate()
                self.fail(out + err)
            if self.sql("select count(*) from pg_stat_activity where datname=current_database() and pid <> pg_backend_pid() and state='active' and query like '%pg_sleep(%';") == '1':
                return
            time.sleep(0.2)
        self.fail('Migration did not enter the blocking statement')

    def test_interrupted_transaction_is_recoverable(self):
        self.command('migrate')
        self.add_migration('CREATE TABLE interrupted_probe(id integer); SELECT pg_sleep(15);')
        process = subprocess.Popen(['python3', str(self.root / 'scripts/migrate.py'), 'migrate'], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.communicate(timeout=60))
        self.wait_for_sleep(process)
        containers = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=whatte.migration.run=' + self.db,
                                              '--filter', 'ancestor=' + FLYWAY_IMAGE], text=True).split()
        self.assertEqual(len(containers), 1)
        subprocess.run(['docker', 'kill', containers[0]], check=True, capture_output=True)
        process.communicate(timeout=20)
        self.assertNotEqual(process.returncode, 0)
        # PostgreSQL may finish a running statement before noticing client death.
        # Reconcile the server session/transaction before declaring recovery.
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.sql("select count(*) from pg_stat_activity where datname=current_database() and pid <> pg_backend_pid();") == '0':
                break
            time.sleep(0.2)
        else:
            self.fail('Disconnected migration session did not terminate within 45s')
        self.assertEqual(self.sql("select to_regclass('interrupted_probe') is null;"), 't')
        self.assertEqual(self.sql("select count(*) from flyway_schema_history where version='2';"), '0')
        self.assertEqual(self.command('migrate')['migrationsExecuted'], 1)

    def test_existing_baseline_skips_v1_and_pins_hash(self):
        self.sql((self.root / 'migrations/sql/V1__baseline.sql').read_text())
        self.env['MIGRATION_ENVIRONMENT'] = 'production'
        self.command('migrate', good=False)
        self.command('baseline', good=False)
        path, receipt = self.receipt('baseline')
        self.command('baseline', extra=['--approval-file', str(path)])
        self.assertEqual(self.sql("select type from flyway_schema_history where version='1';"), 'BASELINE')
        self.assertEqual(self.command('migrate')['migrationsExecuted'], 0)
        self.command('baseline', good=False, extra=['--approval-file', str(path)])
        v1 = self.root / 'migrations/sql/V1__baseline.sql'
        v1.write_text(v1.read_text() + '\n-- changed skipped V1\n')
        manifest_path = self.root / 'migrations/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['migrations'][0]['sha256'] = digest(v1)
        manifest_path.write_text(json.dumps(manifest))
        self.command('validate', good=False)

    def test_production_risky_approval_is_exact(self):
        self.command('migrate')
        self.add_migration('CREATE TABLE risky_probe(id integer);', risk='destructive')
        self.env['MIGRATION_ENVIRONMENT'] = 'production'
        self.command('migrate', good=False)
        path, receipt = self.receipt('migrate')
        self.command('migrate', good=False, extra=['--approval-file', str(path)])
        self.assertEqual(self.sql("select to_regclass('risky_probe') is null;"), 't')
        receipt['approved_migrations'] = {'V2__test.sql': digest(self.root / 'migrations/sql/V2__test.sql')}
        path.write_text(json.dumps(receipt))
        self.assertEqual(self.command('migrate', extra=['--approval-file', str(path)])['migrationsExecuted'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
