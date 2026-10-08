#!/usr/bin/env python3
"""Run one offline candidate with bounded Docker execution and dedicated audit access."""

import argparse
import json
import os
from pathlib import Path

from backend.services.research_container import ResourceLimits
from backend.services.research_runner import run_research_experiment
from backend.services.research_writer import research_writer_connection


def _load(path, limit):
    with path.open('rb') as stream:
        encoded = stream.read(limit + 1)
    if len(encoded) > limit:
        raise ValueError("input_file_limit_exceeded")
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("JSON input must be an object")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "dataset", "baseline", "output-root"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--learned-state", type=Path)
    for name in ("experiment-id", "hypothesis", "image"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--partition", choices=("train", "validation", "test"), default="validation")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--cpus", type=float, default=1.0)
    parser.add_argument("--memory-mb", type=int, default=512)
    parser.add_argument("--pids", type=int, default=64)
    parser.add_argument("--tmp-mb", type=int, default=32)
    parser.add_argument("--output-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--input-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args()
    dsn = os.getenv("WHATTE_RESEARCH_DATABASE_URL")
    if not dsn:
        parser.error("WHATTE_RESEARCH_DATABASE_URL is required; production DATABASE_URL is never used")
    try:
        limits = ResourceLimits(args.timeout_seconds, args.cpus, args.memory_mb, args.pids,
                                args.tmp_mb, args.output_bytes, args.input_bytes)
        result = run_research_experiment(
            learned_state=_load(args.learned_state, limits.input_bytes) if args.learned_state else None,
            config=_load(args.config, limits.input_bytes), dataset=_load(args.dataset, limits.input_bytes),
            baseline=_load(args.baseline, limits.input_bytes), experiment_id=args.experiment_id,
            hypothesis=args.hypothesis, image=args.image, output_root=args.output_root,
            partition=args.partition, limits=limits,
            test_access_granted=os.getenv("WHATTE_RESEARCH_TEST_ACCESS") == "granted",
            connection_factory=lambda: research_writer_connection(dsn),
        )
    except Exception:
        # Driver errors may contain connection details; never print them.
        parser.exit(1, "research run failed; inspect private receipt if created\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
