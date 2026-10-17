#!/usr/bin/env python3
"""Emit read-only decision-to-outcome evidence as JSON."""

import argparse
from datetime import date
import json
import sys

from psycopg import Error as DatabaseError

from backend.services.calibration_records import (
    DEFAULT_GAP_LIMIT,
    MAX_GAP_LIMIT,
    generate_calibration_records,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--date-from", required=True, type=date.fromisoformat)
    parser.add_argument("--date-to", required=True, type=date.fromisoformat)
    parser.add_argument("--timezone")
    parser.add_argument("--report", choices=("calibration", "feedback-completeness"),
                        default="calibration")
    parser.add_argument("--gap-limit", type=int, default=DEFAULT_GAP_LIMIT,
                        help=f"Maximum gaps per list (0–{MAX_GAP_LIMIT})")
    args = parser.parse_args()
    if args.date_to < args.date_from:
        parser.error("date-to must be on or after date-from")
    if not 0 <= args.gap_limit <= MAX_GAP_LIMIT:
        parser.error(f"gap-limit must be between 0 and {MAX_GAP_LIMIT}")
    try:
        result = generate_calibration_records(
            user_id=args.user_id, date_from=args.date_from,
            date_to=args.date_to, timezone=args.timezone, gap_limit=args.gap_limit,
        )
    except DatabaseError:
        # Never turn a failed read into a successful empty report or expose DSNs.
        print(json.dumps({"status": "read_error", "reason_code": "database_read_failed"}))
        sys.exit(1)
    if args.report == "feedback-completeness":
        result = {
            **{key: result[key] for key in (
                "user_id", "date_from", "date_to", "timezone", "generated_at",
            )},
            **result["feedback_completeness"],
        }
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
