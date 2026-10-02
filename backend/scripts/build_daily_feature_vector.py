#!/usr/bin/env python3
"""Print one read-only, versioned daily feature vector as of a cutoff time."""

import argparse
from datetime import date, datetime
import json

from backend.services.daily_feature_vector import build_daily_feature_vector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--local-date", required=True, type=date.fromisoformat)
    parser.add_argument("--cutoff-at", required=True, type=datetime.fromisoformat)
    parser.add_argument("--timezone")
    args = parser.parse_args()
    result = build_daily_feature_vector(
        user_id=args.user_id, local_date=args.local_date,
        cutoff_at=args.cutoff_at, timezone_name=args.timezone,
    )
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
