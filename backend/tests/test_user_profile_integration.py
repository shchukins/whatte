import os
from datetime import date

import pytest

from backend.db import get_conn
from backend.services.user_profile_service import ProfileChange, get_profile, save_profile_value, resolve_activity_profile
from test_metrics_smoke_integration import _cleanup, _seed_test_data, TEST_USER_ID, TEST_ACTIVITY_ID

pytestmark = pytest.mark.skipif(not os.getenv('RUN_DB_TESTS'), reason='Requires isolated PostgreSQL test database')


@pytest.fixture
def seeded_profile():
    _cleanup()
    _seed_test_data()
    try:
        yield
    finally:
        with get_conn() as conn:
            for table in ['user_profile_value', 'activity_response_metrics', 'daily_training_load', 'daily_fitness_state', 'load_state_daily_v2', 'readiness_daily']:
                conn.execute(f'delete from {table} where user_id=%s', (TEST_USER_ID,))
        _cleanup()


def test_dated_ftp_weight_and_correction(seeded_profile):
    save_profile_value(TEST_USER_ID, ProfileChange(metric='ftp', value=222, effective_from=date(2026, 7, 25)))
    save_profile_value(TEST_USER_ID, ProfileChange(metric='weight', value=73.5, effective_from=date(2026, 8, 1)))
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Europe/Moscow midnight is 21:00 UTC on the preceding date.
            for start, expected in [('2026-07-24 20:59:59+00', 200), ('2026-07-24 21:00:00+00', 222), ('2026-08-02 00:00:00+00', 222)]:
                cur.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', (start, TEST_ACTIVITY_ID))
                assert resolve_activity_profile(cur, TEST_USER_ID, TEST_ACTIVITY_ID)[0] == expected
    save_profile_value(TEST_USER_ID, ProfileChange(metric='ftp', value=223, effective_from=date(2026, 7, 25)))
    data = get_profile(TEST_USER_ID)
    assert len(data['history']) == 2
    assert data['current']['ftp']['value'] == 223
    assert data['current']['weight']['value'] == 73.5
    assert data['pending_from'] == date(2026, 7, 25)


def test_unchanged_ftp_does_not_schedule_recompute(seeded_profile):
    change = ProfileChange(metric='ftp', value=222, effective_from=date(2026, 7, 25))
    save_profile_value(TEST_USER_ID, change)
    with get_conn() as conn:
        conn.execute('update user_profile_value set needs_recompute=false where user_id=%s', (TEST_USER_ID,))
    save_profile_value(TEST_USER_ID, change)
    assert get_profile(TEST_USER_ID)['pending_from'] is None


def test_recompute_updates_stored_metrics_and_readiness_through_rest_days(seeded_profile):
    from backend.services.pipeline_service import compute_and_store_activity_metrics
    from backend.services.user_profile_service import recompute_profile_history, local_today
    with get_conn() as conn:
        conn.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', ('2026-07-26 12:00:00+00', TEST_ACTIVITY_ID))
    before = compute_and_store_activity_metrics(TEST_ACTIVITY_ID)
    save_profile_value(TEST_USER_ID, ProfileChange(metric='ftp', value=222, effective_from=date(2026, 7, 25)))
    assert recompute_profile_history(TEST_USER_ID) == 1
    assert get_profile(TEST_USER_ID)['pending_from'] is None
    with get_conn() as conn:
        after = conn.execute('select tss from activity_metrics where strava_activity_id=%s', (TEST_ACTIVITY_ID,)).fetchone()[0]
        assert after == pytest.approx(before['tss'] * (200 / 222) ** 2)
        assert conn.execute('select count(*) from readiness_daily where user_id=%s and date=%s', (TEST_USER_ID, local_today())).fetchone()[0] > 0
    assert recompute_profile_history(TEST_USER_ID) == 0


def test_first_ftp_without_legacy_profile_and_no_future_leak(seeded_profile):
    from backend.services.pipeline_service import compute_and_store_activity_metrics
    with get_conn() as conn:
        conn.execute('delete from user_training_profile where user_id=%s', (TEST_USER_ID,))
    save_profile_value(TEST_USER_ID, ProfileChange(metric='ftp', value=222, effective_from=date(2026, 7, 25)))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', ('2026-07-24 12:00:00+00', TEST_ACTIVITY_ID))
            assert resolve_activity_profile(cur, TEST_USER_ID, TEST_ACTIVITY_ID)[0] is None
            cur.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', ('2026-07-26 12:00:00+00', TEST_ACTIVITY_ID))
    result = compute_and_store_activity_metrics(TEST_ACTIVITY_ID)
    assert result['tss'] is not None
    assert all(v is None for v in result['power_zones_s'].values())
    assert all(v is None for v in result['hr_zones_s'].values())


def test_weight_only_does_not_schedule_load_recompute(seeded_profile):
    save_profile_value(TEST_USER_ID, ProfileChange(metric='weight', value=73.5, effective_from=date(2026, 7, 25)))
    assert get_profile(TEST_USER_ID)['pending_from'] is None


def test_profile_lock_rejects_overlapping_mutation(seeded_profile):
    from backend.services.user_profile_service import _profile_lock
    from fastapi import HTTPException
    with _profile_lock(TEST_USER_ID):
        with pytest.raises(HTTPException) as exc:
            save_profile_value(TEST_USER_ID, ProfileChange(metric='ftp', value=222, effective_from=date(2026, 7, 25)))
        assert exc.value.status_code == 409
    save_profile_value(TEST_USER_ID, ProfileChange(metric='ftp', value=222, effective_from=date(2026, 7, 25)))



def test_hr_max_history_cutoff_correction_and_independent_zones(seeded_profile):
    save_profile_value(TEST_USER_ID, ProfileChange(metric='hr_max', value=195, effective_from=date(2026, 7, 25)))
    save_profile_value(TEST_USER_ID, ProfileChange(metric='hr_max', value=198, effective_from=date(2026, 8, 1)))
    with get_conn() as conn:
        with conn.cursor() as cur:
            for start, expected in [('2026-07-24 20:59:59+00', 190), ('2026-07-24 21:00:00+00', 195), ('2026-08-02 00:00:00+00', 198)]:
                cur.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', (start, TEST_ACTIVITY_ID))
                resolved = resolve_activity_profile(cur, TEST_USER_ID, TEST_ACTIVITY_ID)
                assert resolved[:2] == (200, expected)
                assert resolved[2:] == (110, 150, 180, 210, 240, 280, 120, 140, 155, 170)
    save_profile_value(TEST_USER_ID, ProfileChange(metric='hr_max', value=196, effective_from=date(2026, 8, 1)))
    data = get_profile(TEST_USER_ID)
    assert len(data['history']) == 2
    assert data['current']['hr_max']['value'] == 196
    assert data['pending_from'] == date(2026, 7, 25)


def test_hr_max_missing_before_first_entry_without_legacy_profile(seeded_profile):
    with get_conn() as conn:
        conn.execute('delete from user_training_profile where user_id=%s', (TEST_USER_ID,))
    save_profile_value(TEST_USER_ID, ProfileChange(metric='hr_max', value=195, effective_from=date(2026, 7, 25)))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', ('2026-07-24 20:59:59+00', TEST_ACTIVITY_ID))
            assert resolve_activity_profile(cur, TEST_USER_ID, TEST_ACTIVITY_ID) == (None,) * 12
            cur.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', ('2026-07-24 21:00:00+00', TEST_ACTIVITY_ID))
            assert resolve_activity_profile(cur, TEST_USER_ID, TEST_ACTIVITY_ID) == (None, 195) + (None,) * 10


def test_hr_max_recompute_refreshes_provenance_without_rescaling_zones(seeded_profile):
    from backend.services.pipeline_service import compute_and_store_activity_metrics
    from backend.services.user_profile_service import recompute_profile_history
    with get_conn() as conn:
        conn.execute('update strava_activity_raw set start_date=%s where strava_activity_id=%s', ('2026-07-26 12:00:00+00', TEST_ACTIVITY_ID))
    before = compute_and_store_activity_metrics(TEST_ACTIVITY_ID)
    change = ProfileChange(metric='hr_max', value=195, effective_from=date(2026, 7, 25))
    save_profile_value(TEST_USER_ID, change)
    assert recompute_profile_history(TEST_USER_ID) == 1
    assert get_profile(TEST_USER_ID)['pending_from'] is None
    after = compute_and_store_activity_metrics(TEST_ACTIVITY_ID)
    assert after['tss'] == pytest.approx(before['tss'])
    assert after['power_zones_s'] == before['power_zones_s']
    assert after['hr_zones_s'] == before['hr_zones_s']
    with get_conn() as conn:
        assert conn.execute('select raw_json from activity_metrics where strava_activity_id=%s', (TEST_ACTIVITY_ID,)).fetchone()[0]['hr_max'] == 195
    save_profile_value(TEST_USER_ID, change)
    assert get_profile(TEST_USER_ID)['pending_from'] is None


def test_hr_max_migration_rerun_preserves_corrections_and_validates_database(seeded_profile):
    from pathlib import Path
    from psycopg.errors import CheckViolation
    migration = (Path(__file__).parents[2] / 'db-init/020_user_profile_hr_max.sql').read_text()
    with get_conn() as conn:
        conn.execute(migration, prepare=False)
        conn.execute(migration, prepare=False)
    data = get_profile(TEST_USER_ID)
    assert data['current']['hr_max']['value'] == 190
    assert data['pending_from'] is None
    save_profile_value(TEST_USER_ID, ProfileChange(metric='hr_max', value=195, effective_from=date(2026, 1, 1)))
    with get_conn() as conn:
        conn.execute(migration, prepare=False)
    assert get_profile(TEST_USER_ID)['current']['hr_max']['value'] == 195
    for metric, value in [('hr_max', 190.5), ('hr_max', 251), ('hr_max', 0), ('unknown', 190), ('ftp', 1001), ('weight', 501)]:
        with pytest.raises(CheckViolation), get_conn() as conn:
            conn.execute('insert into user_profile_value (user_id, metric, effective_from, value) values (%s, %s, %s, %s)', (TEST_USER_ID, metric, date(2026, 2, 1), value))
