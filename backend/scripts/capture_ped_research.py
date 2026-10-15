"""Capture current PED inputs prospectively into a private immutable local file."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from backend.db import get_conn
from backend.services.rpe_history_service import _SELECT, FIELDS
from backend.services.ped_research import SNAPSHOT_VERSION, validate_snapshots
from backend.services.recovery_prediction import canonical_hash


def capture(user_id, activity_id):
    computed = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read, read only')
            cur.execute(_SELECT+' and r.strava_activity_id = %s', (user_id, activity_id))
            raw = cur.fetchone()
            if raw is None:
                raise ValueError('owned_activity_missing')
            target = dict(zip(FIELDS, raw))
            cur.execute('select elapsed_time_s from strava_activity_raw where user_id = %s and strava_activity_id = %s',
                        (user_id, activity_id))
            elapsed = cur.fetchone()[0]
            if type(elapsed) is not int or elapsed <= 0:
                raise ValueError('completion_time_unavailable')
            completed = target['started_at']+timedelta(seconds=elapsed)
            # Filter timestamp evidence before LIMIT, preserving PED v1 policy.
            cur.execute(_SELECT+''' and r.start_date < %s
                and r.start_date >= %s - interval '365 days' and r.activity_type = %s
                and obs.scale_version = 'rpe_1_10' and er.effective_score between 1 and 10
                and r.updated_at < %s and m.computed_at < %s and obs.received_at < %s
                and er.resolved_at < %s and (obs.observed_at is null or obs.observed_at < %s)
                order by r.start_date desc, r.strava_activity_id desc limit 200''',
                (user_id, target['started_at'], target['started_at'], target['sport'], *([target['started_at']]*5)))
            candidates = [dict(zip(FIELDS, row)) for row in cur.fetchall()]
    state = json.loads(json.dumps({'as_of_status': 'prospective_capture', 'user_id': user_id,
        'computed_at': computed, 'captured_at': datetime.now(timezone.utc), 'completed_at': completed,
        'target': target, 'candidates': candidates}, default=str))
    result = {'version': SNAPSHOT_VERSION, 'snapshots': [{**state, 'snapshot_hash': canonical_hash(state)}]}
    validate_snapshots(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--activity-id', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = capture(args.user_id, args.activity_id)
        # O_EXCL and 0600 at creation; caller chooses an existing private parent.
        if args.output.parent.stat().st_mode & 0o077:
            raise ValueError('private_parent_required')
        with os.fdopen(os.open(args.output, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as stream:
            json.dump(result, stream, sort_keys=True, allow_nan=False)
    except Exception:
        print(json.dumps({'status': 'failed', 'reason': 'ped_capture_unavailable'}))
        return 1
    print(json.dumps({'status': 'captured', 'evidence_hash': canonical_hash(result)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
