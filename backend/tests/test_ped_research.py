"""Synthetic pipeline proofs; fixtures are not evidence of PED benefit."""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from backend.services import ped_research as ped
from backend.services.recovery_prediction import timestamp, canonical_hash
from backend.services.research_runner import run_ped_study
from backend.services import research_runner as runner
from backend.services.research_container import DockerExecutor
from scripts.research_worker import process_request
from test_recovery_prediction import dataset_fixture, FIT_TIME


def snapshot(index):
    start = timestamp('2026-01-01T12:00:00+00:00')+timedelta(days=index)
    def session(activity_id, day, rpe):
        return {'activity_id': activity_id, 'user_id': 'fixture-user', 'started_at': day.isoformat(),
                'sport': 'Ride', 'duration_s': 3600, 'np_w': 200, 'if': 0.8, 'vi': 1.05,
                'rpe': rpe, 'scale': 'rpe_1_10', 'source': 'web', 'rpe_observed_at': None,
                **{k: (day+timedelta(hours=2)).isoformat() for k in ped.AVAILABILITY_FIELDS}}
    state = {'user_id': 'fixture-user', 'as_of_status': 'prospective_capture',
             'completed_at': (start+timedelta(hours=1)).isoformat(),
             'computed_at': (start+timedelta(hours=3)).isoformat(),
             'captured_at': (start+timedelta(hours=3)).isoformat(),
             'target': session(1000+index, start, [4, 6, 8][(index//4)%3]),
             'candidates': [session(-i, start-timedelta(days=30+i), 5) for i in range(1, 4)]}
    return {**state, 'snapshot_hash': canonical_hash(state)}


def fixture():
    return dataset_fixture(validation_days=30)[0], {'version': ped.SNAPSHOT_VERSION,
                                 'snapshots': [snapshot(i) for i in range(-7, 72)]}


def rehash_snapshot(item):
    item['snapshot_hash'] = canonical_hash({k: v for k, v in item.items() if k != 'snapshot_hash'})


def test_latest_rolling_persistent_and_future_edits_never_enter():
    dataset, evidence = fixture()
    row = dataset['partitions']['train'][0]
    snapshots = ped.validate_snapshots(evidence)
    result = ped.covariates(row, snapshots)
    assert result['latest'] == 3
    assert result['rolling'] is not None and result['persistent'] in (0, 1)
    past = [s for s in snapshots if s['captured_at'] <= timestamp(row['feature']['cutoff_at'])]
    assert result == ped.covariates(row, past)
    for s in past:
        s['captured_at'] = timestamp(row['feature']['cutoff_at'])+timedelta(seconds=1)
    assert ped.covariates(row, past) == dict.fromkeys(ped.VARIANTS)
    one = ped.validate_snapshots({'version': ped.SNAPSHOT_VERSION, 'snapshots': [snapshot(-1)]})
    assert ped.covariates(row, one)['rolling'] is None
    one[0]['activity_id'] = row['activity_id']
    assert ped.covariates(row, one)['latest'] is None


@pytest.mark.parametrize('mutation,reason', [
    (lambda s: s.update(as_of_status='current_records'), 'as_of_state'),
    (lambda s: s.update(completed_at=s['captured_at']+'bad'), 'timestamp'),
    (lambda s: s['target'].update(user_id='other'), 'as_of_state'),
    (lambda s: s['target'].update(resolution_at='2027-01-01T00:00:00+00:00'), 'after_capture'),
    (lambda s: s['candidates'][0].update(user_id='other'), 'cross_user'),
])
def test_snapshot_fail_closed(mutation, reason):
    item = snapshot(0)
    mutation(item)
    rehash_snapshot(item)
    with pytest.raises(ValueError, match=reason):
        ped.validate_snapshots({'version': ped.SNAPSHOT_VERSION, 'snapshots': [item]})


def test_snapshot_hash_scale_and_baseline_late_edit():
    item = snapshot(0)
    item['target']['rpe'] = 9
    with pytest.raises(ValueError, match='hash_invalid'):
        ped.validate_snapshots({'version': ped.SNAPSHOT_VERSION, 'snapshots': [item]})
    for mutation in (lambda s: s['target'].update(scale='legacy_1_5'),
                     lambda s: s['candidates'][0].update(resolution_at=s['captured_at'])):
        item = snapshot(0)
        mutation(item)
        rehash_snapshot(item)
        assert ped.validate_snapshots({'version': ped.SNAPSHOT_VERSION, 'snapshots': [item]})[0]['ped'] is None


def test_fitting_uses_only_train_targets_and_refuses_late_receipts():
    dataset, evidence = fixture()
    report, jobs = ped.prepare_study(dataset, evidence, fit_as_of=FIT_TIME)
    assert len(jobs) == 12
    assert len(report['results']) == 12
    changed = deepcopy(dataset)
    for row in changed['partitions']['validation']:
        row['outcome']['targets']['next_day_recovery']['score'] = 5
    from test_recovery_prediction import rehash
    rehash(changed)
    _, new_jobs = ped.prepare_study(changed, evidence, fit_as_of=FIT_TIME)
    assert [j['state'] for j in jobs] == [j['state'] for j in new_jobs]
    row = changed['partitions']['train'][0]
    row['outcome']['targets']['next_day_recovery']['updated_at'] = '2027-01-01T00:00:00+00:00'
    rehash(changed)
    with pytest.raises(ValueError, match='train_label_after_fit'):
        ped.prepare_study(changed, evidence, fit_as_of=FIT_TIME)
    with pytest.raises(ValueError, match='before_validation'):
        ped.prepare_study(dataset, evidence, fit_as_of='2027-01-01T00:00:00+00:00')
    with pytest.raises(PermissionError):
        ped.prepare_study(dataset, evidence, fit_as_of=FIT_TIME, partition='test')


def test_run_reuses_worker_evaluator_receipts_and_audit(tmp_path, monkeypatch):
    dataset, evidence = fixture()
    requests, audit = [], []
    def execute(self, request, directory):
        requests.append(request)
        return {'metadata': {'failure_reason': None, 'cleanup_succeeded': True},
                'response': process_request(request)}
    monkeypatch.setattr(DockerExecutor, 'execute', execute)
    monkeypatch.setattr(runner, 'create_research_experiment', lambda **kw: audit.append(kw))
    monkeypatch.setattr(runner, 'finish_research_experiment', lambda **kw: audit.append(kw))
    report = run_ped_study(dataset=dataset, evidence=evidence, fit_as_of=FIT_TIME,
        experiment_id='ped-proof', output_root=tmp_path/'private', image='sha256:'+'a'*64,
        connection_factory=lambda: None)
    assert len(requests) == 12
    assert all('outcome' not in json.dumps(r) and 'updated_at' not in json.dumps(r) for r in requests)
    assert report['recommendation'] == 'refine'
    assert audit[-1]['status'] == 'candidate'
    assert all(r['metrics']['evaluator_version'] == 'baseline_evaluator_v2' for r in report['results'])
    assert all('brier_score' not in json.dumps(r['metrics']) for r in report['results'])
    first = report['results'][0]
    assert first['uncertainty']['paired_days'] == 30
    assert len(first['uncertainty']['mae_delta_interval_95']) == 2
    assert len(first['uncertainty']['time_windows']) == 3
    assert (tmp_path/'private'/'ped-proof'/'study-report.json').stat().st_mode & 0o777 == 0o600
    assert run_ped_study(dataset=dataset, evidence=evidence, fit_as_of=FIT_TIME,
        experiment_id='repeat', output_root=tmp_path/'private', image='sha256:'+'a'*64)['report_hash'] == report['report_hash']
    with pytest.raises(FileExistsError):
        run_ped_study(dataset=dataset, evidence=evidence, fit_as_of=FIT_TIME,
            experiment_id='repeat', output_root=tmp_path/'private', image='sha256:'+'a'*64)


def test_missing_evidence_records_insufficient_without_execution(tmp_path, monkeypatch):
    dataset = dataset_fixture()[0]
    monkeypatch.setattr(DockerExecutor, 'execute', lambda *a, **k: pytest.fail('container started'))
    report = run_ped_study(dataset=dataset, evidence={'version': ped.SNAPSHOT_VERSION, 'snapshots': []},
                          fit_as_of=FIT_TIME, experiment_id='no-capture', output_root=tmp_path/'private')
    assert report['recommendation'] == 'insufficient_evidence'
    assert all(r['train_paired_days'] == 0 and r['metrics'] is None for r in report['results'])
    assert json.loads((tmp_path/'private'/'no-capture'/'receipt.json').read_text())['status'] == 'rejected'


def test_worker_forgery_records_failed_not_metrics(tmp_path, monkeypatch):
    dataset, evidence = fixture()
    monkeypatch.setattr(DockerExecutor, 'execute', lambda *a, **k: {
        'metadata': {'failure_reason': None, 'cleanup_succeeded': True},
        'response': {'protocol_version': 'ped_research_execution_v1', 'status': 'ok', 'result': []}})
    with pytest.raises(ValueError, match='execution_failed'):
        run_ped_study(dataset=dataset, evidence=evidence, fit_as_of=FIT_TIME,
                      experiment_id='forged', output_root=tmp_path/'private', image='sha256:'+'a'*64)
    assert json.loads((tmp_path/'private'/'forged'/'receipt.json').read_text())['status'] == 'failed'


def test_cli_bounded_private_artifact_and_aggregate_stdout(tmp_path):
    dataset = dataset_fixture()[0]
    for name, value in [('dataset', dataset), ('evidence', {'version': ped.SNAPSHOT_VERSION, 'snapshots': []})]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value))
    command = [sys.executable, '-m', 'scripts.run_ped_study', '--dataset', str(tmp_path/'dataset.json'),
               '--evidence', str(tmp_path/'evidence.json'), '--fit-as-of', FIT_TIME,
               '--experiment-id', 'cli', '--output-root', str(tmp_path/'private')]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15,
                            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
    assert result.returncode == 2
    assert json.loads(result.stdout)['recommendation'] == 'insufficient_evidence'
    assert 'fixture-user' not in result.stdout and 'observation_id' not in result.stdout


def test_singular_covariate_is_not_an_implicit_zero():
    with pytest.raises(ValueError, match='singular'):
        ped.fit_pair([(i, 1, i) for i in range(30)])


def test_duplicate_comparables_cannot_inflate_minimum_sample():
    item = snapshot(0)
    item['candidates'] = [item['candidates'][0]]*3
    rehash_snapshot(item)
    with pytest.raises(ValueError, match='duplicate_or_unbounded'):
        ped.validate_snapshots({'version': ped.SNAPSHOT_VERSION, 'snapshots': [item]})


def test_capture_reads_one_transaction_and_never_writes(monkeypatch):
    from scripts import capture_ped_research as capture
    from backend.services.rpe_history_service import FIELDS
    item = snapshot(0)
    def native(row):
        result = deepcopy(row)
        for key in ('started_at', *ped.AVAILABILITY_FIELDS):
            result[key] = timestamp(result[key])
        return tuple(result.get(key) for key in FIELDS)
    answers = [[native(item['target'])], [(3600,)], [native(c) for c in item['candidates']]]
    queries = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, query, params=None):
            queries.append((query, params))
            if query.strip().startswith('select'):
                self.rows = answers.pop(0)
        def fetchone(self): return self.rows[0]
        def fetchall(self): return self.rows
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def cursor(self): return Cursor()
    monkeypatch.setattr(capture, 'get_conn', lambda: Connection())
    result = capture.capture('fixture-user', 1000)
    assert queries[0][0] == 'set transaction isolation level repeatable read, read only'
    assert len(queries) == 4
    assert 'obs.received_at <' in queries[-1][0]
    assert queries[-1][1][0] == 'fixture-user'
    assert ped.validate_snapshots(result)[0]['ped'] == -1


def test_insufficient_holdout_retains_metrics_with_explicit_coverage(tmp_path, monkeypatch):
    dataset = dataset_fixture(validation_days=10)[0]
    evidence = {'version': ped.SNAPSHOT_VERSION, 'snapshots': [snapshot(i) for i in range(-7, 52)]}
    monkeypatch.setattr(DockerExecutor, 'execute', lambda self, request, directory: {
        'metadata': {'failure_reason': None, 'cleanup_succeeded': True}, 'response': process_request(request)})
    report = run_ped_study(dataset=dataset, evidence=evidence, fit_as_of=FIT_TIME,
                          experiment_id='few-heldout', output_root=tmp_path/'private', image='sha256:'+'a'*64)
    assert report['recommendation'] == 'insufficient_evidence'
    assert all(r['reason'] == 'insufficient_paired_coverage' for r in report['results'])
    assert all(r['uncertainty']['paired_days'] == 10 for r in report['results'])
    assert all(r['uncertainty']['mae_delta_interval_95'] is None for r in report['results'])
