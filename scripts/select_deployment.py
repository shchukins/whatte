"""Select only a completed exact-SHA release; no production credentials needed."""
import json
import os
from pathlib import Path
import subprocess
from deploy_policy import eligible_run


def gh(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    sha = os.environ.get('SELECTED_SHA') or gh(f'repos/{repo}/commits/main')['sha']
    run_id = os.environ.get('SOURCE_RUN_ID')
    if not run_id:
        runs = gh(f'repos/{repo}/actions/workflows/backend-ci.yml/runs?head_sha={sha}&event=push&per_page=100')['workflow_runs']
        completed = [r for r in runs if r['conclusion'] == 'success']
        if not completed:
            raise ValueError('No successful CI for selected SHA')
        run_id = str(completed[0]['id'])
    run = gh(f'repos/{repo}/actions/runs/{run_id}')
    jobs = gh(f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100')['jobs']
    eligible_run(run, jobs, sha)
    if gh(f'repos/{repo}/commits/main')['sha'] != sha:
        raise ValueError('Selected release is no longer main')
    artifact = Path('release-artifact')
    subprocess.run(['gh', 'run', 'download', run_id, '--name', f'release-{sha}', '--dir', str(artifact)], check=True)
    manifest = json.loads((artifact / 'release-manifest.json').read_text())
    if manifest['git_sha'] != sha or manifest['ci_run'] != run['html_url']:
        raise ValueError('Release artifact does not match CI')
    request = {'mode': os.environ.get('DEPLOY_MODE', 'dry-run'), 'manifest': manifest}
    Path('deployment-request.json').write_text(json.dumps(request))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'sha={sha}\n')


if __name__ == '__main__':
    main()
