"""Bounded Docker execution; no credentials or candidate-controlled commands."""

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
import time
import uuid


@dataclass(frozen=True)
class ResourceLimits:
    timeout_seconds: int = 120
    cpus: float = 1.0
    memory_mb: int = 512
    pids: int = 64
    tmp_mb: int = 32
    output_bytes: int = 8 * 1024 * 1024
    input_bytes: int = 64 * 1024 * 1024

    def __post_init__(self):
        # Engineering safety bounds, not model parameters. One container at a time.
        bounds = {"timeout_seconds": (1, 3600), "memory_mb": (64, 4096),
                  "pids": (16, 256), "tmp_mb": (1, 256),
                  "output_bytes": (1024, 16 * 1024 * 1024),
                  "input_bytes": (1024, 128 * 1024 * 1024)}
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"invalid resource limit: {name}")
        if type(self.cpus) not in (int, float) or not math.isfinite(self.cpus) or not 0.1 <= self.cpus <= 4:
            raise ValueError("invalid resource limit: cpus")

    def as_dict(self):
        return asdict(self)


def validate_image(image):
    if not isinstance(image, str) or not re.fullmatch(r"(?:[A-Za-z0-9._/:-]+@)?sha256:[0-9a-f]{64}", image):
        raise ValueError("image must be pinned by SHA-256 digest or local image ID")
    return image


class DockerExecutor:
    def __init__(self, image, limits):
        self.image = validate_image(image)
        self.limits = limits

    def command(self, name, input_dir):
        # Only trusted operator inputs select image/limits; JSON cannot add flags.
        return ["docker", "create", "--pull=never", "--name", name,
                "--network=none", "--read-only", "--user=65534:65534",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--init",
                "--restart=no", f"--cpus={self.limits.cpus}",
                f"--memory={self.limits.memory_mb}m", f"--memory-swap={self.limits.memory_mb}m",
                f"--pids-limit={self.limits.pids}", "--log-driver=none",
                f"--tmpfs=/tmp:rw,noexec,nosuid,nodev,size={self.limits.tmp_mb}m",
                "--mount", f"type=bind,src={input_dir},dst=/input,readonly",
                "--entrypoint=python", self.image, "-m", "scripts.research_worker"]

    def execute(self, request, directory):
        directory = Path(directory)
        directory.mkdir(mode=0o700)
        input_dir = directory / "input"
        input_dir.mkdir(mode=0o755)
        input_dir.chmod(0o755)
        encoded = json.dumps(request, sort_keys=True, allow_nan=False).encode()
        if len(encoded) > self.limits.input_bytes:
            raise ValueError("container_input_limit_exceeded")
        request_path = input_dir / "request.json"
        request_path.write_bytes(encoded)
        request_path.chmod(0o644)
        if "," in str(input_dir.resolve()):
            raise ValueError("bind_mount_path_contains_comma")
        name = "whatte-research-" + uuid.uuid4().hex
        started = time.monotonic()
        deadline = started + self.limits.timeout_seconds
        metadata = {"container_name": name, "image": self.image, "limits": self.limits.as_dict(),
                    "exit_code": None, "timed_out": False, "oom_killed": False,
                    "failure_reason": None, "cleanup_succeeded": False}
        process = None
        creation_attempted = False
        stdout_path, stderr_path = directory / "stdout.json", directory / "stderr.log"
        stdout_path.touch(mode=0o600)
        stderr_path.touch(mode=0o600)
        try:
            info = subprocess.run(["docker", "info", "--format", "{{json .}}"],
                                  capture_output=True, timeout=max(0.01, min(5, deadline - time.monotonic())))
            environment = json.loads(info.stdout) if info.returncode == 0 else {}
            if environment.get("OSType") != "linux" or str(environment.get("CgroupVersion")) != "2":
                raise ValueError("linux_cgroup_v2_required")
            creation_attempted = True
            created = subprocess.run(self.command(name, input_dir.resolve()),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     timeout=max(0.01, deadline - time.monotonic()), check=False)
            if created.returncode:
                metadata["failure_reason"] = "container_create_failed"
            elif b"not support" in (created.stderr or b"").lower():
                metadata["failure_reason"] = "container_limits_not_supported"
            else:
                process = subprocess.Popen(["docker", "start", "--attach", name],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                sizes = {}
                with selectors.DefaultSelector() as selector, stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                    for stream, target in ((process.stdout, out), (process.stderr, err)):
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, selectors.EVENT_READ, target)
                        sizes[stream] = 0
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            metadata.update(timed_out=True, failure_reason="wall_clock_timeout")
                            break
                        for key, _ in selector.select(min(remaining, 0.1)):
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            available = self.limits.output_bytes - sizes[key.fileobj]
                            key.data.write(chunk[:available])
                            sizes[key.fileobj] += len(chunk)
                            if sizes[key.fileobj] > self.limits.output_bytes:
                                metadata["failure_reason"] = "container_output_limit_exceeded"
                                break
                        if metadata["failure_reason"]:
                            break
                if not metadata["failure_reason"]:
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    inspected = subprocess.run(["docker", "inspect", "--format", "{{json .State}}", name],
                                               capture_output=True, timeout=5, check=False)
                    state = json.loads(inspected.stdout) if inspected.returncode == 0 else {}
                    metadata.update(exit_code=state.get("ExitCode"), oom_killed=state.get("OOMKilled", False))
                    if not state:
                        metadata["failure_reason"] = "container_inspect_failed"
                    elif metadata["oom_killed"]:
                        metadata["failure_reason"] = "container_oom_killed"
                    elif process.returncode != 0 or metadata["exit_code"] != 0:
                        metadata["failure_reason"] = "candidate_process_failed"
        except subprocess.TimeoutExpired:
            metadata.update(timed_out=True, failure_reason="wall_clock_timeout")
        except KeyboardInterrupt:
            metadata["failure_reason"] = "runner_interrupted"
        except (OSError, ValueError):
            metadata["failure_reason"] = "container_execution_failed"
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdout, process.stderr):
                    stream.close()
            try:
                if metadata["failure_reason"] and process is not None:
                    subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=5)
                    inspected = subprocess.run(["docker", "inspect", "--format", "{{json .State}}", name],
                                               capture_output=True, timeout=5)
                    if inspected.returncode == 0:
                        state = json.loads(inspected.stdout)
                        metadata.update(exit_code=state.get("ExitCode"), oom_killed=state.get("OOMKilled", False))
                if creation_attempted:
                    removed = subprocess.run(["docker", "rm", "--force", name],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    metadata["cleanup_succeeded"] = removed.returncode == 0
                else:
                    metadata["cleanup_succeeded"] = True
            except (OSError, ValueError, subprocess.TimeoutExpired):
                # Removal is attempted even if kill/inspection failed.
                try:
                    removed = subprocess.run(["docker", "rm", "--force", name],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    metadata["cleanup_succeeded"] = removed.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if not metadata["cleanup_succeeded"]:
                metadata["failure_reason"] = "container_cleanup_failed"
            metadata["duration_ms"] = round((time.monotonic() - started) * 1000)
            metadata["stdout_reference"] = str(stdout_path.resolve())
            metadata["stderr_reference"] = str(stderr_path.resolve())
        response = None
        try:
            response = json.loads(stdout_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if not metadata["failure_reason"]:
                metadata["failure_reason"] = "invalid_worker_response"
        return {"metadata": metadata, "response": response}
