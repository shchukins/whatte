#!/usr/bin/python3
"""Root-owned SSH forced-command gate, run as the existing deployment user."""
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import urllib.request

REPO = Path('/srv/human-engine')
STATE = Path('/home/sergey/.config/whatte-release')


def run(*args):
    return subprocess.check_output(args, cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()


def api(path):
    with urllib.request.urlopen('https://api.github.com/repos/shchukins/whatte/' + path, timeout=30) as response:
        return json.load(response)


def main():
    if os.environ.get('SSH_ORIGINAL_COMMAND') != 'whatte-deploy-v1':
        raise ValueError('Only the fixed deployment request is supported')
    request = json.loads(sys.stdin.buffer.read(65537))
    manifest = request['manifest']
    sha = manifest['git_sha']
    if not re.fullmatch('[0-9a-f]{40}', sha) or request['mode'] not in {'dry-run', 'deploy'}:
        raise ValueError('Invalid request')
    run_match = re.fullmatch(r'https://github.com/shchukins/whatte/actions/runs/([0-9]+)', manifest['ci_run'])
    if not run_match:
        raise ValueError('Invalid CI run')
    with open(STATE / 'deploy.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run('git', 'fetch', 'origin', 'main')
        if run('git', 'rev-parse', 'origin/main') != sha:
            raise ValueError('Stale release')
        if run('git', 'status', '--porcelain'):
            raise ValueError('Dirty production checkout')
        # Extract tracked CI-tested main files; incoming JSON never supplies code.
        with tempfile.TemporaryDirectory(prefix='deployment-', dir=STATE) as directory:
            archive = subprocess.Popen(['git', 'archive', sha], cwd=REPO, stdout=subprocess.PIPE)
            extraction = subprocess.run(['tar', '-x', '-C', directory], stdin=archive.stdout, check=True)
            archive.stdout.close()
            if archive.wait() != 0:
                raise ValueError('Cannot extract selected release')
            sys.path.insert(0, str(Path(directory) / 'scripts'))
            from deploy_policy import eligible_run
            ci_id = run_match[1]
            eligible_run(api('actions/runs/' + ci_id), api('actions/runs/' + ci_id + '/jobs?per_page=100')['jobs'], sha)
            request_file = Path(directory) / 'request.json'
            request_file.write_text(json.dumps(request))
            request_file.chmod(0o600)
            # A runner disconnect must not cancel migrations/rollout. The engine
            # inherits the lock and writes phases durably before each mutation.
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            outcome = subprocess.run([sys.executable, str(Path(directory) / 'scripts/deploy.py'),
                                      '--request', str(request_file), '--source', directory],
                                     pass_fds=(lock.fileno(),), start_new_session=True,
                                     capture_output=True, text=True)
            print(outcome.stdout, end='')
            return outcome.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        print(json.dumps({'phase': 'gate_rejected'}))
        raise SystemExit(1)
