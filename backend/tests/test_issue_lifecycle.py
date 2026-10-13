"""Rehearse verified issue closure without GitHub writes or production access."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import issue_lifecycle as lifecycle


def evidence(previous='b' * 40, sha='a' * 40):
    return {'contract_version': 'whatte_delivery_v1', 'outcome': 'SUCCESS',
            'phase': 'success', 'mode': 'deploy', 'git_sha': sha,
            'previous_sha': previous, 'completed_at': '2026-10-13T00:00:00Z',
            'migration_status': 'succeeded', **dict.fromkeys(lifecycle.CHECKS, True)}


@pytest.mark.parametrize('change', [
    {'outcome': 'FAILED'}, {'outcome': 'ROLLED_BACK'}, {'outcome': 'REQUIRES_INTERVENTION'},
    {'phase': 'docs_skipped'}, {'mode': 'dry-run'}, {'git_sha': 'c' * 40},
    {'migration_status': 'not_started'}, {'completed_at': None},
    *[{key: False} for key in lifecycle.CHECKS],
])
def test_incomplete_delivery_never_reaches_github(change):
    result = {**evidence(), **change}
    with pytest.raises(ValueError):
        lifecycle.close_issues(result, 'a' * 40, 'owner/repo',
                               lambda _: pytest.fail('must not read issues'),
                               lambda _: pytest.fail('must not close issues'))


def test_only_explicit_terminal_signals_count():
    assert lifecycle.completed_issues([
        'work (#190)\n\nWhatte-Issue-Ref: #190',
        'finish\n\nWhatte-Issue-Complete: #190\nWhatte-Issue-Complete: #191',
        'more work\n\nWhatte-Issue-Ref: #191',
        'discussion\n\nWhatte-Issue-Complete: #192\n\nStill incomplete.',
    ]) == [190]
    assert lifecycle.completed_issues(['Fixes #190', 'refs #190']) == []


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=CI', '-c',
                                       'user.email=ci@example.com', *args], text=True).strip()
    git('init', '-q')
    git('commit', '--allow-empty', '-qm', 'running release')
    previous = git('rev-parse', 'HEAD')
    for message in ('work\n\nWhatte-Issue-Ref: #190',
                    'completed intermediate release\n\nWhatte-Issue-Complete: #190',
                    'other task\n\nWhatte-Issue-Ref: #191',
                    'finish\n\nWhatte-Issue-Complete: #192'):
        git('commit', '--allow-empty', '-qm', message)
    return evidence(previous, git('rev-parse', 'HEAD'))


def test_full_range_skipped_releases_and_duplicate_events(history):
    states = {190: 'open', 191: 'open', 192: 'open'}
    writes = []
    def read(n):
        return {'number': n, 'state': states[n], 'repository_url': 'https://api.github.com/repos/owner/repo'}
    def close(n):
        writes.append(n)
        states[n] = 'closed'
    for _ in range(2):
        result = lifecycle.close_issues(history, history['git_sha'], 'owner/repo', read, close)
        assert result['eligible'] == [190, 192]
    assert writes == [190, 192]
    assert states[191] == 'open'


def test_pr_or_foreign_issue_fails_before_any_closure(history):
    def read(n):
        return {'number': n, 'state': 'open', 'repository_url': 'https://api.github.com/repos/owner/repo',
                **({'pull_request': {}} if n == 192 else {})}
    with pytest.raises(ValueError):
        lifecycle.close_issues(history, history['git_sha'], 'owner/repo', read,
                               lambda _: pytest.fail('identity prevalidation must happen first'))


def test_partial_api_failure_can_retry_without_duplicate_closure(history):
    states = {190: 'open', 192: 'open'}
    def read(n):
        return {'number': n, 'state': states[n], 'repository_url': 'https://api.github.com/repos/owner/repo'}
    def fail(n):
        if n == 192:
            raise RuntimeError('GitHub unavailable')
        states[n] = 'closed'
    with pytest.raises(RuntimeError):
        lifecycle.close_issues(history, history['git_sha'], 'owner/repo', read, fail)
    writes = []
    lifecycle.close_issues(history, history['git_sha'], 'owner/repo', read, writes.append)
    assert writes == [192]


def test_activation_guard(monkeypatch):
    monkeypatch.delenv('PRODUCTION_AUTO_CLOSE', raising=False)
    with pytest.raises(ValueError, match='activated'):
        lifecycle.main()
