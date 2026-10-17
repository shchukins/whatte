"""Exercise the shared #77 query against real PostgreSQL date/join semantics."""

from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import os
from zoneinfo import ZoneInfo

import pytest

from backend.db import get_conn
from backend.services import calibration_records as calibration


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_DB_TESTS"), reason="Requires isolated PostgreSQL test database",
)


@pytest.mark.parametrize("day,zone_name", [
    (date(2026, 9, 1), "Europe/Moscow"),
    (date(2026, 3, 29), "Europe/Berlin"),
    (date(2026, 10, 25), "Europe/Berlin"),
])
def test_completeness_canonical_selection_local_boundaries_and_d_plus_1(monkeypatch, day, zone_name):
    zone = ZoneInfo(zone_name)
    start = datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    now = datetime.combine(day + timedelta(days=2), datetime.min.time(), tzinfo=zone)
    with get_conn() as conn:
        for table in ("strava_activity_raw", "activity_metrics", "activity_subjective_feedback",
                      "activity_rpe_observation", "activity_rpe_resolution", "decision_context_snapshot"):
            conn.execute(f"create temporary table {table} (like public.{table} including all)")
        cases = [
            (1, "synthetic", start, False, False, None),
            (2, "synthetic", end - timedelta(microseconds=1), False, False, None),
            (3, "synthetic", start - timedelta(microseconds=1), False, False, None),
            (4, "synthetic", end, False, False, None),
            (5, "synthetic", start, False, False, 1),
            (6, "synthetic", start, True, False, None),
            (7, "synthetic", start, False, True, None),
            (8, "other", start, False, False, None),
        ]
        for aid, user, timestamp, deleted, excluded, duplicate in cases:
            conn.execute(
                """insert into strava_activity_raw
                   (id, strava_activity_id, strava_athlete_id, user_id, start_date,
                    activity_type, is_deleted, is_excluded, duplicate_of_activity_id, raw_json)
                   values (%s, %s, 1, %s, %s, 'Run', %s, %s, %s, '{}'::jsonb)""",
                (aid, aid, user, timestamp, deleted, excluded, duplicate),
            )
        conn.execute("""insert into activity_rpe_observation
            (id, user_id, canonical_activity_id, source, score)
            values (1, 'synthetic', 1, 'strava', 8),
                   (2, 'synthetic', 1, 'web', 3),
                   (3, 'synthetic', 2, 'web', 6)""")
        conn.execute("""insert into activity_rpe_resolution
            (canonical_activity_id, user_id, effective_score, effective_source, disagreement)
            values (1, 'synthetic', 8, 'strava', true), (2, 'synthetic', 9, 'web', false)""")
        conn.execute("""insert into activity_subjective_feedback
            (id, user_id, canonical_activity_id, strava_activity_id,
             activity_date, feedback_type, feedback_score, feedback_value, source)
            values (1, 'synthetic', 2, 2, %s, 'post_ride_rpe', 4, 'hard', 'telegram'),
                   (2, 'synthetic', null, null, %s, 'next_day_recovery', 4, 'fresh', 'web'),
                   (3, 'other', null, null, %s, 'next_day_recovery', 1, 'exhausted', 'web')""",
                     (day, day + timedelta(days=1), day + timedelta(days=1)))
        conn.commit()
        monkeypatch.setattr(calibration, "get_conn", lambda: nullcontext(conn))

        def build():
            return calibration.generate_calibration_records(
                user_id="synthetic", date_from=day, date_to=day,
                timezone=zone_name, generated_at=now,
            )

        result = build()
        assert conn.execute("show transaction_read_only").fetchone()[0] == "on"
        conn.rollback()
        assert [r["activity_id"] for r in result["records"]] == [1, 2]
        assert all(r["activity_local_date"] == day for r in result["records"])
        assert all(r["decision"] is None for r in result["records"])
        counts = result["feedback_completeness"]
        assert counts["canonical_workout_count"] == 2
        assert counts["rpe"]["usable_current"] == counts["rpe"]["incompatible"] == 1
        assert counts["rpe"]["compatible_legacy_observation_count"] == 1
        assert counts["rpe"]["source_disagreement_count"] == 1
        assert counts["training_day_count"] == counts["next_day_recovery"]["usable"] == 1
        assert result["records"][0]["next_day_recovery"]["target_local_date"] == day + timedelta(days=1)
        assert result == build()
        conn.rollback()
        conn.execute("delete from activity_subjective_feedback where id = 2")
        conn.commit()
        assert build()["feedback_completeness"]["next_day_recovery"]["missing"] == 1
