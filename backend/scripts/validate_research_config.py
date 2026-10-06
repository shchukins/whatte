#!/usr/bin/env python3
"""Export the research schema/default config or validate a JSON config."""

import argparse
import json
from pathlib import Path

from backend.services.research_parameter_space import (
    baseline_candidate_config, candidate_config_hash, candidate_config_schema,
    validate_candidate_config,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--schema", action="store_true")
    source.add_argument("--baseline", action="store_true")
    source.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.schema:
        result = candidate_config_schema()
    elif args.baseline:
        result = baseline_candidate_config()
    else:
        try:
            with args.config.open(encoding="utf-8") as file:
                config = validate_candidate_config(json.load(file))
        except (OSError, ValueError) as error:
            parser.error(str(error))
        result = {"candidate_config": config, "candidate_config_hash": candidate_config_hash(config)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
