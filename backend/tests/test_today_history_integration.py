import os
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.db import get_conn
from backend.today import history_service as diary
from backend.today import service as today

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
        for table in ("strava_activity_raw", "activity_rpe_observation", "activity_rpe_resolution", "activity_metrics"):
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
        conn.execute("update strava_activity_raw set activity_type = 'Ride'")
        conn.execute("update strava_activity_raw set activity_type = 'Run' where strava_activity_id = 3")
        conn.execute("""insert into activity_metrics
            (id, user_id, strava_activity_id, version, tss, normalized_power, intensity_factor)
            values (1, 'athlete', 1, 'v1', 40, 180, 0.8),
                   (2, 'athlete', 1, 'future', null, null, null),
                   (3, 'other', 2, 'v1', 40, 180, 0.8),
                   (4, 'athlete', 2, 'future', 40, 180, 0.8),
                   (5, 'athlete', 3, 'v1', 40, 180, 0.8)""")
        conn.commit()
        monkeypatch.setattr(diary, "get_conn", lambda: nullcontext(conn))
        monkeypatch.setattr(today, "get_conn", lambda: nullcontext(conn))
        with conn.transaction():
            conn.execute("set transaction read only")
            result = diary.get_diary_activities("athlete", target)
            assert [a.activity_id for a in result] == [3, 2, 1]
            assert [a.duration_s for a in result] == [1200, 0, None]
            assert result[-1].start_time.date() == start.date()
            assert result[0].start_time.date() == target
            assert result[0].name == "Activity"
            assert result[0].sport_type == "Run"
            assert [a.load_status for a in result] == [
                "Вид спорта пока не поддерживается", "Нет необходимых данных мощности",
                "Подходит для расчёта нагрузки"]
            assert [a.load_assessment.included for a in result] == [False, None, True]
            assert [a.load_assessment.reason for a in result] == [
                "unsupported_sport", "unavailable_metrics_record", None]
            for activity in result:
                selected = today.get_today_activity("athlete", preferred_activity_id=activity.activity_id)
                assert selected.load_status == activity.load_status
            assert today.get_today_activity("athlete", preferred_activity_id=6) is None
            assert today.get_today_activity("athlete", preferred_activity_id=7) is None
            assert today.get_today_activity("athlete", preferred_activity_id=8) is None
            assert today.get_today_activity("athlete", preferred_activity_id=9) is None
            assert today.get_today_activity("absent") is None
            assert result[0].rpe_score is result[0].rpe_source is result[0].rpe_web_score is None
            assert (result[1].rpe_score, result[1].rpe_source, result[1].rpe_disagreement) == (4, "web", True)
            assert (result[1].rpe_web_score, result[1].rpe_strava_score, result[1].rpe_telegram_score) == (4, 8, 7)
            assert diary.get_diary_activities("absent", target) == []


def test_personal_rpe_history_uses_effective_source_scale_and_owner(monkeypatch):
    from backend.services import rpe_history_service as history

    with get_conn() as conn:
        for table in ('strava_activity_raw', 'activity_metrics',
                      'activity_rpe_observation', 'activity_rpe_resolution'):
            conn.execute(f'create temporary table {table} (like public.{table} including all)')
        for activity_id in range(1, 11):
            user = 'other' if activity_id == 7 else 'athlete'
            started = datetime(2026, 8, 30, tzinfo=timezone.utc) - timedelta(days=activity_id)
            if activity_id == 8:
                started = datetime(2026, 8, 31, tzinfo=timezone.utc)
            conn.execute(
                """insert into strava_activity_raw
                   (id, strava_activity_id, strava_athlete_id, user_id, start_date,
                    activity_type, raw_json, is_excluded)
                   values (%s, %s, 1, %s, %s, 'Ride', '{}'::jsonb, %s)""",
                (activity_id, activity_id, user, started, activity_id == 9))
            conn.execute(
                """insert into activity_metrics
                   (id, strava_activity_id, user_id, moving_time_s, normalized_power,
                    intensity_factor, variability_index)
                   values (%s, %s, %s, 3600, 200, 0.8, 1.05)""",
                (activity_id, activity_id, user))
            conn.execute(
                """insert into activity_rpe_resolution
                   (canonical_activity_id, user_id, effective_score, effective_source)
                   values (%s, %s, 7, 'strava')""", (activity_id, user))
            # Candidate 5 lacks an observation; candidate 6 has a mismatched score.
            if activity_id != 5:
                conn.execute(
                    """insert into activity_rpe_observation
                       (id, canonical_activity_id, user_id, source, score)
                       values (%s, %s, %s, 'strava', %s)""",
                    (activity_id, activity_id, user, 5 if activity_id == 6 else 7))
        # A foreign observation must not qualify an owner's effective resolution.
        conn.execute("update activity_rpe_observation set user_id='other' where canonical_activity_id=10")
        # A manual value cannot override the mismatched effective Strava observation.
        conn.execute("""insert into activity_rpe_observation
                       (id, canonical_activity_id, user_id, source, score)
                       values (20, 6, 'athlete', 'web', 8)""")
        monkeypatch.setattr(history, 'get_conn', lambda: nullcontext(conn))
        result = history.get_rpe_history('athlete', 1)
        assert result['status'] == 'available'
        assert [row['activity_id'] for row in result['matches']] == [2, 3, 4]
        assert all(row['source'] == 'strava' and row['rpe'] == 7 for row in result['matches'])
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            history.get_rpe_history('other', 1)
        assert exc.value.status_code == 404


def test_effort_deviation_sql_temporal_sources_and_read_only(monkeypatch):
    """Exercise real joins and edit timestamps, without writes from the service."""
    from backend.services import effort_baseline_service as ped
    from backend.services import rpe_history_service as history
    target = datetime(2026, 10, 10, tzinfo=timezone.utc)
    with get_conn() as conn:
        for table in ('strava_activity_raw', 'activity_metrics',
                      'activity_rpe_observation', 'activity_rpe_resolution'):
            conn.execute(f'create temporary table {table} (like public.{table} including all)')
        for activity_id in range(1, 14):
            started = target if activity_id == 1 else target - timedelta(days=activity_id)
            available = started + timedelta(hours=1)
            conn.execute('''insert into strava_activity_raw
                (id, strava_activity_id, user_id, strava_athlete_id, activity_type,
                 start_date, updated_at, raw_json)
                values (%s, %s, 'athlete', 1, 'Ride', %s, %s, '{}'::jsonb)''',
                (activity_id, activity_id, started, available))
            conn.execute('''insert into activity_metrics
                (id, strava_activity_id, user_id, version, moving_time_s,
                 normalized_power, intensity_factor, variability_index, computed_at)
                values (%s, %s, 'athlete', 'v1', 3600, 200, 0.8, 1.05, %s)''',
                (activity_id, activity_id, available))
            conn.execute('''insert into activity_rpe_observation
                (id, canonical_activity_id, user_id, source, score, received_at)
                values (%s, %s, 'athlete', 'strava', %s, %s)''',
                (activity_id, activity_id, 8 if activity_id == 1 else 6, available))
            conn.execute('''insert into activity_rpe_resolution
                (canonical_activity_id, user_id, effective_source, effective_score, resolved_at)
                values (%s, 'athlete', 'strava', %s, %s)''',
                (activity_id, 8 if activity_id == 1 else 6, available))
        # Only 2,3,4 survive. Each rejected row isolates a distinct boundary.
        conn.execute('update activity_rpe_observation set received_at = %s where canonical_activity_id = 5', (target,))
        conn.execute('update activity_metrics set computed_at = %s where strava_activity_id = 6', (target,))
        conn.execute('update strava_activity_raw set updated_at = %s where strava_activity_id = 7', (target,))
        conn.execute('update activity_rpe_resolution set resolved_at = %s where canonical_activity_id = 8', (target,))
        conn.execute("update strava_activity_raw set user_id = 'other' where strava_activity_id = 9")
        conn.execute("update strava_activity_raw set is_deleted = true where strava_activity_id = 10")
        conn.execute("update strava_activity_raw set is_excluded = true where strava_activity_id = 11")
        conn.execute('update strava_activity_raw set duplicate_of_activity_id = 2 where strava_activity_id = 12')
        conn.execute('update activity_rpe_observation set observed_at = %s where canonical_activity_id = 13', (target,))
        # A usable lower-priority source must not replace a late Strava observation.
        conn.execute('''insert into activity_rpe_observation
            (id, canonical_activity_id, user_id, source, score, received_at)
            values (100, 5, 'athlete', 'web', 3, %s)''', (target - timedelta(days=1),))
        conn.commit()
        monkeypatch.setattr(history, 'get_conn', lambda: nullcontext(conn))
        with conn.transaction():
            conn.execute('set transaction read only')
            result = ped.get_effort_deviation('athlete', 1)
            assert result['status'] == 'available'
            assert result['expected_rpe'] == 6 and result['ped'] == 2
            assert result['sample_count'] == 3
            assert {r['activity_id'] for r in result['source_references']} == {2, 3, 4}
            assert result['actual_reference']['source'] == 'strava'
        with conn.transaction():
            conn.execute('update activity_rpe_observation set received_at = %s where canonical_activity_id = 2', (target,))
        with conn.transaction():
            conn.execute('set transaction read only')
            result = ped.get_effort_deviation('athlete', 1)
            assert result['status'] == 'unavailable'
            assert result['ped'] is None and result['sample_count'] == 2


def test_prospective_ped_capture_real_joins_are_read_only(monkeypatch):
    from scripts import capture_ped_research as capture
    from backend.services.ped_research import validate_snapshots
    target = datetime.now(timezone.utc)-timedelta(days=10)
    with get_conn() as conn:
        for table in ('strava_activity_raw', 'activity_metrics',
                      'activity_rpe_observation', 'activity_rpe_resolution'):
            conn.execute(f'create temporary table {table} (like public.{table} including all)')
        for activity_id in range(1, 5):
            started = target-timedelta(days=activity_id)
            available = started+timedelta(hours=2)
            score = 8 if activity_id == 1 else 6
            conn.execute('''insert into strava_activity_raw
                (id, strava_activity_id, user_id, strava_athlete_id, activity_type,
                 start_date, elapsed_time_s, updated_at, raw_json)
                values (%s, %s, 'athlete', 1, 'Ride', %s, 3600, %s, '{}'::jsonb)''',
                (activity_id, activity_id, started, available))
            conn.execute('''insert into activity_metrics
                (id, strava_activity_id, user_id, version, moving_time_s,
                 normalized_power, intensity_factor, variability_index, computed_at)
                values (%s, %s, 'athlete', 'v1', 3600, 200, 0.8, 1.05, %s)''',
                (activity_id, activity_id, available))
            conn.execute('''insert into activity_rpe_observation
                (id, canonical_activity_id, user_id, source, score, received_at)
                values (%s, %s, 'athlete', 'strava', %s, %s)''',
                (activity_id, activity_id, score, available))
            conn.execute('''insert into activity_rpe_resolution
                (canonical_activity_id, user_id, effective_source, effective_score, resolved_at)
                values (%s, 'athlete', 'strava', %s, %s)''',
                (activity_id, score, available))
        conn.commit()
        monkeypatch.setattr(capture, 'get_conn', lambda: nullcontext(conn))
        with conn.transaction():
            evidence = capture.capture('athlete', 1)
            assert validate_snapshots(evidence)[0]['ped'] == 2
            assert conn.execute("select current_setting('transaction_read_only')").fetchone()[0] == 'on'
            assert conn.execute("select current_setting('transaction_isolation')").fetchone()[0] == 'repeatable read'
