#!/usr/bin/env python3
"""Export a versioned temporal research dataset to stdout."""

import argparse
import csv
from datetime import date
import json
import os
import sys

from backend.services.temporal_dataset import TemporalSplit, generate_temporal_dataset


def _rows(dataset):
    for partition in dataset["partitions"].values():
        yield from partition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--train-start", required=True, type=date.fromisoformat)
    parser.add_argument("--train-end", required=True, type=date.fromisoformat)
    parser.add_argument("--validation-end", required=True, type=date.fromisoformat)
    parser.add_argument("--test-end", required=True, type=date.fromisoformat)
    parser.add_argument("--timezone")
    parser.add_argument("--format", choices=("json", "jsonl", "csv"), default="json")
    parser.add_argument("--include-test", action="store_true")
    args = parser.parse_args()
    if args.include_test and os.getenv("WHATTE_RESEARCH_TEST_ACCESS") != "granted":
        parser.error("test export requires WHATTE_RESEARCH_TEST_ACCESS=granted")
    dataset = generate_temporal_dataset(
        user_id=args.user_id,
        split=TemporalSplit(args.train_start, args.train_end, args.validation_end, args.test_end),
        timezone_name=args.timezone,
        include_test=args.include_test,
        test_access_granted=args.include_test,
    )
    if args.format == "json":
        print(json.dumps(dataset, default=str, ensure_ascii=False, sort_keys=True, indent=2))
    elif args.format == "jsonl":
        for row in _rows(dataset):
            print(json.dumps(row, default=str, ensure_ascii=False, sort_keys=True))
    else:
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=("observation_id", "partition", "activity_id", "activity_start_at",
                        "activity_local_date", "row_hash", "feature_json", "outcome_json"),
        )
        writer.writeheader()
        for row in _rows(dataset):
            writer.writerow({
                "observation_id": row["observation_id"],
                "partition": row["partition"],
                "activity_id": row["activity_id"],
                "activity_start_at": row["activity_start_at"],
                "activity_local_date": row["activity_local_date"],
                "row_hash": row["row_hash"],
                "feature_json": json.dumps(row["feature"], sort_keys=True),
                "outcome_json": json.dumps(row["outcome"], sort_keys=True),
            })


if __name__ == "__main__":
    main()
