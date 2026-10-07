"""Real Docker/cgroup checks using an explicitly synthetic worker image."""

import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest

from backend.services.research_container import DockerExecutor, ResourceLimits

pytestmark = pytest.mark.skipif(os.getenv("RUN_DOCKER_TESTS") != "1", reason="Set RUN_DOCKER_TESTS=1 on a Linux Docker host")


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    directory = tmp_path_factory.mktemp("synthetic-worker")
    (directory / "Dockerfile").write_text("FROM python:3.11-slim\nWORKDIR /app\nCOPY worker.py scripts/research_worker.py\n")
    (directory / "worker.py").write_text(textwrap.dedent('''
        import json, os, socket, sys, time
        from pathlib import Path
        request = json.loads(Path('/input/request.json').read_text())
        operation = request['operation']
        if operation == 'timeout':
            time.sleep(30)
        if operation == 'exception':
            raise RuntimeError('synthetic_exception')
        if operation == 'oom':
            value = bytearray(256 * 1024 * 1024)
        if operation == 'output':
            print('x' * 100000)
        if operation == 'success':
            assert os.getuid() == 65534
            assert not Path('/var/run/docker.sock').exists()
            assert 'DATABASE_URL' not in os.environ
            assert 'WHATTE_RESEARCH_DATABASE_URL' not in os.environ
            try:
                Path('/app/forbidden').write_text('x')
            except OSError:
                pass
            else:
                raise AssertionError('writable root')
            try:
                Path('/input/forbidden').write_text('x')
            except OSError:
                pass
            else:
                raise AssertionError('writable input')
            assert int(Path('/sys/fs/cgroup/memory.max').read_text()) == 64 * 1024 * 1024
            assert int(Path('/sys/fs/cgroup/pids.max').read_text()) == 16
            assert Path('/sys/fs/cgroup/cpu.max').read_text().split()[0] != 'max'
            with socket.socket() as connection:
                connection.settimeout(0.5)
                assert connection.connect_ex(('1.1.1.1', 443)) != 0
            print(json.dumps({'status': 'synthetic_success'}))
    '''))
    built = subprocess.run(["docker", "build", "-q", str(directory)], check=True, capture_output=True, text=True, timeout=180)
    image_id = built.stdout.strip().splitlines()[-1]
    yield image_id
    subprocess.run(["docker", "image", "rm", image_id], check=True, capture_output=True, timeout=30)


@pytest.mark.parametrize("operation, failure", [
    ("success", None), ("exception", "candidate_process_failed"),
    ("timeout", "wall_clock_timeout"), ("oom", "container_oom_killed"),
    ("output", "container_output_limit_exceeded"),
])
def test_real_container_limits_cleanup_and_isolation(image, tmp_path, operation, failure):
    # First container creation on a fresh CI daemon can exceed three seconds.
    # Keep the deliberately sleeping worker on a short deadline; allow cold
    # image/container setup for the other scenarios without changing runner limits.
    timeout = 3 if operation == "timeout" else 15
    executor = DockerExecutor(image, ResourceLimits(timeout_seconds=timeout, memory_mb=64, pids=16, output_bytes=1024))
    result = executor.execute({"operation": operation}, tmp_path / "stage")
    metadata = result["metadata"]
    assert metadata["failure_reason"] == failure
    assert metadata["cleanup_succeeded"]
    assert Path(metadata["stdout_reference"]).stat().st_size <= 1024
    assert Path(metadata["stderr_reference"]).stat().st_size <= 1024
    inspected = subprocess.run(["docker", "inspect", metadata["container_name"]], capture_output=True, timeout=5)
    assert inspected.returncode != 0
    if operation == "success":
        assert result["response"] == {"status": "synthetic_success"}
    if operation == "oom":
        assert metadata["oom_killed"]
    if operation == "timeout":
        assert metadata["timed_out"]
