"""Record an immutable image and validate rendered production Compose parity."""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATTERN = r"ghcr\.io/shchukins/whatte-backend@sha256:[0-9a-f]{64}"


def validate_compose(config: dict, image: str) -> None:
    if not re.fullmatch(IMAGE_PATTERN, image):
        raise ValueError("production requires the exact GHCR digest")
    services = config["services"]
    for name in ("backend", "worker"):
        service = services[name]
        if service["image"] != image or service.get("build") or service.get("volumes"):
            raise ValueError(f"{name} must use the shared image without builds/mounts")
    if services["worker"]["command"] != ["python", "-m", "backend.worker"]:
        raise ValueError("unexpected worker command")
    db_volume = config["volumes"]["postgres_data"]
    network = config["networks"]["default"]
    if db_volume.get("name") != "human-engine_postgres_data" or not db_volume.get("external"):
        raise ValueError("production database volume must already exist")
    if network.get("name") != "human-engine_default" or not network.get("external"):
        raise ValueError("production network must already exist")
    for name in ("backend", "worker", "postgres"):
        if services[name]["container_name"] != f"human-engine-{name}":
            raise ValueError("container identity mismatch")
    backend_port = services["backend"]["ports"]
    if len(backend_port) != 1 or backend_port[0].get("host_ip") != "127.0.0.1" or str(backend_port[0]["published"]) != "8000":
        raise ValueError("backend must retain the loopback edge binding")
    db_ports = services["postgres"]["ports"]
    if len(db_ports) != 1 or not db_ports[0].get("host_ip", "").startswith("100.") or str(db_ports[0]["published"]) != "5432":
        raise ValueError("database must retain its reviewed Tailscale binding")
    if not any(v.get("type") == "volume" and v.get("source") == "postgres_data" and v.get("target") == "/var/lib/postgresql/data" for v in services["postgres"]["volumes"]):
        raise ValueError("database data mount mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ci-run", required=True)
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("invalid Git SHA")
    validate_compose(json.loads(args.compose.read_text()), args.image)
    files = ("compose.production.yaml", "backend/requirements.lock", "migrations/manifest.json", "migrations/sql/V1__baseline.sql")
    manifest = {
        "contract_version": "whatte_release_v1",
        "git_sha": args.sha,
        "image": args.image,
        "platform": "linux/amd64",
        "ci_run": args.ci_run,
        "files_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
    }
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
