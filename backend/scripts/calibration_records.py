#!/usr/bin/env python3
"""Emit read-only decision-to-outcome evidence as JSON."""

import argparse
from datetime import date
import json

from backend.services.calibration_records import generate_calibration_records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--date-from", required=True, type=date.fromisoformat)
    parser.add_argument("--date-to", required=True, type=date.fromisoformat)
    parser.add_argument("--timezone")
    args = parser.parse_args()
    result = generate_calibration_records(
        user_id=args.user_id, date_from=args.date_from,
        date_to=args.date_to, timezone=args.timezone,
    )
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
