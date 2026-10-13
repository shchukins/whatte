"""Close explicitly completed issues from a verified production change range."""
import json
import os
from pathlib import Path
import re
import subprocess

CHECKS = ('database_unchanged', 'shared_image_verified', 'worker_verified',
          'local_health', 'public_health', 'route_boundaries', 'functional_smoke')


def completed_issues(messages):
    # Oldest first; a later Ref revokes an earlier completion signal.
    signals = {}
    for message in messages:
        trailers = message.strip().split('\n\n')[-1]
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*: .+', line)
               for line in trailers.splitlines()):
            continue
        for line in trailers.splitlines():
            match = re.fullmatch(r'Whatte-Issue-(Ref|Complete): #([1-9][0-9]*)', line.strip())
            if match:
                signals[int(match[2])] = match[1]
    return sorted(number for number, signal in signals.items() if signal == 'Complete')


def verified_range(result, selected):
    if (result.get('contract_version') != 'whatte_delivery_v1'
            or result.get('outcome') != 'SUCCESS' or result.get('phase') != 'success'
            or result.get('mode') != 'deploy' or result.get('git_sha') != selected
            or not re.fullmatch('[0-9a-f]{40}', selected)
            or not re.fullmatch('[0-9a-f]{40}', result.get('previous_sha', ''))
            or not result.get('completed_at') or result.get('migration_status') != 'succeeded'
            or any(result.get(check) is not True for check in CHECKS)):
        raise ValueError('Issue closure requires complete production verification')
    return result['previous_sha'], selected


def gh(path, **fields):
    command = ['gh', 'api', path]
    if fields:
        command += ['--method', 'PATCH']
        for key, value in fields.items():
            command += ['-f', f'{key}={value}']
    return json.loads(subprocess.check_output(command, text=True))


def close_issues(result, selected, repo, read_issue, close_issue):
    previous, sha = verified_range(result, selected)
    subprocess.run(['git', 'merge-base', '--is-ancestor', previous, sha], check=True)
    messages = subprocess.check_output(['git', 'log', '--reverse', '--format=%B%x00',
                                        f'{previous}..{sha}'], text=True).split('\x00')
    candidates = completed_issues(messages)
    # Validate all identities before any writes; PRs share issue numbers.
    issues = [(number, read_issue(number)) for number in candidates]
    for number, issue in issues:
        if ('pull_request' in issue or issue.get('number') != number
                or issue.get('repository_url') != f'https://api.github.com/repos/{repo}'):
            raise ValueError('Completion signal must identify a local issue')
    closed = []
    for number, issue in issues:
        if issue['state'] == 'open':
            close_issue(number)
            closed.append(number)
    return {'eligible': candidates, 'closed': closed}


def main():
    if os.environ.get('PRODUCTION_AUTO_CLOSE') != 'true':
        raise ValueError('Automatic closure has not been activated')
    repo = os.environ['GITHUB_REPOSITORY']
    result = json.loads(Path('deployment-result.json').read_text())
    report = close_issues(result, os.environ['SELECTED_SHA'], repo,
                          lambda n: gh(f'repos/{repo}/issues/{n}'),
                          lambda n: gh(f'repos/{repo}/issues/{n}', state='closed', state_reason='completed'))
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write('\nIssue lifecycle: ' + json.dumps(report) + '\n')


if __name__ == '__main__':
    main()
