"""Eligibility shared by the Actions selector and the host deployment engine."""
import re

REQUIRED_JOBS = {'unit-tests', 'db-integration-tests', 'publish-release'}
RUNTIME_PATHS = ('backend/', 'migrations/', 'sql/', 'db-init/', 'scripts/', 'ops/deploy/')


def eligible_run(run, jobs, sha):
    if (not re.fullmatch(r'[0-9a-f]{40}', sha) or run.get('head_sha') != sha
            or run.get('head_branch') != 'main' or run.get('event') != 'push'
            or run.get('path') != '.github/workflows/backend-ci.yml'
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'):
        raise ValueError('Release requires successful exact-SHA main push CI')
    passed = {job['name'] for job in jobs if job.get('conclusion') == 'success'}
    if not REQUIRED_JOBS <= passed:
        raise ValueError('Required release checks did not succeed')


def requires_rollout(paths):
    return any(p.startswith(RUNTIME_PATHS) or p == 'compose.production.yaml' for p in paths)


def ordering(selected, main, previous, is_ancestor):
    # Actions pending runs can be replaced/reordered. Recheck under the host lock.
    if selected != main:
        raise ValueError('Stale release: selected SHA is no longer main')
    if previous != selected and not is_ancestor(previous, selected):
        raise ValueError('Release would regress or diverge from production')
