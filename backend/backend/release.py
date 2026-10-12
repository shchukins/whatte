"""Image-owned revision metadata; environment variables cannot spoof it."""

import json
import re
from pathlib import Path


def read_release(path: Path | None = None) -> dict[str, str | None]:
    metadata = path or Path(__file__).resolve().parents[1] / "release.json"
    if not metadata.exists():
        return {"git_sha": None}  # A development checkout is not a release image.
    sha = json.loads(metadata.read_text())["git_sha"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid baked release revision")
    return {"git_sha": sha}


RELEASE = read_release()
