#!/usr/bin/env python3
"""Recompute manual-only personal physiology features for one local date."""

import argparse
from datetime import date
import json

from backend.services.personal_physiology_features import (
    recompute_personal_physiology_features_for_date,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--local-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    result = recompute_personal_physiology_features_for_date(
        user_id=args.user_id, local_date=args.local_date,
    )
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
