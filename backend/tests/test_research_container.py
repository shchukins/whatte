"""Exercise real pipe draining and deadline termination without a Docker daemon."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from backend.services import research_container as containers


@pytest.mark.parametrize("mode, expected", [
    ("ok", None), ("sleep", "wall_clock_timeout"),
    ("large", "container_output_limit_exceeded"), ("error", "candidate_process_failed"),
])
def test_stream_bounding_timeout_exit_and_cleanup(tmp_path, monkeypatch, mode, expected):
    real_popen = subprocess.Popen
    children, calls = [], []
    scripts = {"ok": "print('{}')", "sleep": "import time; time.sleep(30)",
               "large": "print('x' * 100000)", "error": "raise RuntimeError('synthetic')"}
    def popen(command, **kw):
        child = real_popen([sys.executable, "-c", scripts[mode]], **kw)
        children.append(child)
        return child
    def run(command, **kw):
        calls.append(command)
        stdout = b""
        if command[1] == "info":
            stdout = json.dumps({"OSType": "linux", "CgroupVersion": "2"}).encode()
        if command[1] == "inspect":
            stdout = json.dumps({"ExitCode": children[0].returncode, "OOMKilled": False}).encode()
        return subprocess.CompletedProcess(command, 0, stdout, b"")
    monkeypatch.setattr(containers.subprocess, "Popen", popen)
    monkeypatch.setattr(containers.subprocess, "run", run)
    result = containers.DockerExecutor("sha256:" + "a" * 64,
                                      containers.ResourceLimits(timeout_seconds=1, output_bytes=1024)).execute({}, tmp_path / "stage")
    assert result["metadata"]["failure_reason"] == expected
    assert result["metadata"]["cleanup_succeeded"]
    assert children[0].poll() is not None
    assert Path(result["metadata"]["stdout_reference"]).stat().st_size <= 1024
    assert Path(result["metadata"]["stderr_reference"]).stat().st_size <= 1024
    assert any(c[:3] == ["docker", "rm", "--force"] for c in calls)
    if expected == "wall_clock_timeout":
        assert any(c[:2] == ["docker", "kill"] for c in calls)
        assert result["metadata"]["timed_out"]


def test_no_container_created_without_linux_cgroup_limits(tmp_path, monkeypatch):
    calls = []
    def run(command, **kw):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b'{"OSType":"linux","CgroupVersion":"1"}', b'')
    monkeypatch.setattr(containers.subprocess, "run", run)
    result = containers.DockerExecutor("sha256:" + "a" * 64, containers.ResourceLimits()).execute({}, tmp_path / "stage")
    assert result["metadata"]["failure_reason"] == "container_execution_failed"
    assert result["metadata"]["cleanup_succeeded"]
    assert len(calls) == 1


def test_input_limit_prevents_process_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(containers.subprocess, "run", lambda *a, **k: pytest.fail("process started"))
    with pytest.raises(ValueError, match="input_limit"):
        containers.DockerExecutor("sha256:" + "a" * 64, containers.ResourceLimits(input_bytes=1024)).execute(
            {"input": "x" * 2000}, tmp_path / "stage")
