import copy
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.release import read_release

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_manifest", ROOT / "scripts/release_manifest.py")
release_manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_manifest)
IMAGE = "ghcr.io/shchukins/whatte-backend@sha256:" + "a" * 64


def test_version_is_read_only_and_not_environment_controlled(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "b" * 40)
    response = TestClient(app).get("/version")
    assert response.status_code == 200
    assert response.json() == {"git_sha": None}


def test_baked_revision_and_explicit_development_missingness(tmp_path):
    metadata = tmp_path / "release.json"
    assert read_release(metadata) == {"git_sha": None}
    metadata.write_text(json.dumps({"git_sha": "a" * 40}))
    assert read_release(metadata) == {"git_sha": "a" * 40}
    metadata.write_text(json.dumps({"git_sha": "main"}))
    with pytest.raises(ValueError, match="invalid baked"):
        read_release(metadata)


def valid_config():
    return {
        "services": {
            "backend": {"image": IMAGE, "container_name": "human-engine-backend", "ports": [{"host_ip": "127.0.0.1", "published": "8000"}]},
            "worker": {"image": IMAGE, "container_name": "human-engine-worker", "command": ["python", "-m", "backend.worker"]},
            "postgres": {"container_name": "human-engine-postgres", "ports": [{"host_ip": "100.64.0.1", "published": "5432"}], "volumes": [{"type": "volume", "source": "postgres_data", "target": "/var/lib/postgresql/data"}]},
        },
        "volumes": {"postgres_data": {"name": "human-engine_postgres_data", "external": True}},
        "networks": {"default": {"name": "human-engine_default", "external": True}},
    }


def test_existing_data_and_edge_configuration():
    release_manifest.validate_compose(valid_config(), IMAGE)


@pytest.mark.parametrize("service,key,value", [
    ("backend", "volumes", [{"type": "bind", "source": "./backend", "target": "/app"}]),
    ("worker", "image", "ghcr.io/shchukins/whatte-backend:main"),
    ("backend", "build", {"context": "backend"}),
    ("backend", "ports", [{"host_ip": "0.0.0.0", "published": "8000"}]),
    ("postgres", "ports", [{"host_ip": "0.0.0.0", "published": "5432"}]),
    ("postgres", "volumes", []),
])
def test_rejects_mutable_release_and_configuration_regressions(service, key, value):
    config = copy.deepcopy(valid_config())
    config["services"][service][key] = value
    with pytest.raises(ValueError):
        release_manifest.validate_compose(config, IMAGE)


def test_rejects_new_database_volume_and_mutable_tag():
    config = valid_config()
    config["volumes"]["postgres_data"]["external"] = False
    with pytest.raises(ValueError):
        release_manifest.validate_compose(config, IMAGE)
    with pytest.raises(ValueError, match="digest"):
        release_manifest.validate_compose(valid_config(), "ghcr.io/shchukins/whatte-backend:main")
