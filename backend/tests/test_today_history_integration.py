import os
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.db import get_conn
from backend.today import history_service as diary

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_DB_TESTS"), reason="Requires isolated PostgreSQL test database",
)


@pytest.mark.parametrize("target,tz", [
    (date(2026, 8, 30), "Europe/Moscow"),
    (date(2026, 3, 29), "Europe/Berlin"),
    (date(2026, 10, 25), "Europe/Berlin"),
])
def test_diary_sql_filters_boundaries_sources_and_read_only(monkeypatch, target, tz):
    local_tz = ZoneInfo(tz)
    monkeypatch.setattr(diary, "WHATTE_TZ", local_tz)
    start = datetime.combine(target - timedelta(days=13), datetime.min.time(), local_tz)
    end = datetime.combine(target + timedelta(days=1), datetime.min.time(), local_tz)
    start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    with get_conn() as conn:
        # Session-local copies use the real schema/uniqueness constraints and
        # never alter shared test rows. Explicit IDs avoid advancing sequences.
        for table in ("strava_activity_raw", "activity_rpe_observation", "activity_rpe_resolution"):
            conn.execute(f"create temporary table {table} (like public.{table} including all)")
        cases = [
            (1, "athlete", start_utc, False, False, None, None, None),
            (2, "athlete", end_utc - timedelta(seconds=1), False, False, None, 0, 600),
            (3, "athlete", end_utc - timedelta(seconds=1), False, False, None, None, 1200),
            (4, "athlete", start_utc - timedelta(seconds=1), False, False, None, None, None),
            (5, "athlete", end_utc, False, False, None, None, None),
            (6, "other", start_utc, False, False, None, None, None),
            (7, "athlete", start_utc, True, False, None, None, None),
            (8, "athlete", start_utc, False, True, None, None, None),
            (9, "athlete", start_utc, False, False, 1, None, None),
            (10, "athlete", None, False, False, None, None, None),
        ]
        for activity_id, user, timestamp, deleted, excluded, duplicate, moving, elapsed in cases:
            conn.execute(
                """insert into strava_activity_raw
                   (id, strava_activity_id, strava_athlete_id, user_id, start_date,
                    is_deleted, is_excluded, duplicate_of_activity_id,
                    moving_time_s, elapsed_time_s, raw_json)
                   values (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)""",
                (activity_id, activity_id, user, timestamp, deleted, excluded, duplicate, moving, elapsed),
            )
        conn.execute(
            """insert into activity_rpe_resolution
               (canonical_activity_id, user_id, effective_score, effective_source, disagreement)
               values (2, 'athlete', 4, 'web', true), (3, 'other', 9, 'strava', true)""",
        )
        conn.execute(
            """insert into activity_rpe_observation (id, canonical_activity_id, user_id, source, score)
               values (1, 2, 'athlete', 'web', 4), (2, 2, 'athlete', 'strava', 8),
                      (3, 2, 'athlete', 'telegram', 7), (4, 3, 'other', 'web', 9)""",
        )
        conn.commit()
        monkeypatch.setattr(diary, "get_conn", lambda: nullcontext(conn))
        with conn.transaction():
            conn.execute("set transaction read only")
            result = diary.get_diary_activities("athlete", target)
            assert [a.activity_id for a in result] == [3, 2, 1]
            assert [a.duration_s for a in result] == [1200, 0, None]
            assert result[-1].start_time.date() == start.date()
            assert result[0].start_time.date() == target
            assert result[0].name == "Activity"
            assert result[0].sport_type == "Workout"
            assert result[0].rpe_score is result[0].rpe_source is result[0].rpe_web_score is None
            assert (result[1].rpe_score, result[1].rpe_source, result[1].rpe_disagreement) == (4, "web", True)
            assert (result[1].rpe_web_score, result[1].rpe_strava_score, result[1].rpe_telegram_score) == (4, 8, 7)
            assert diary.get_diary_activities("absent", target) == []
