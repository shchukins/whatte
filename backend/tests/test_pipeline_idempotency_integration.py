import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.db import get_conn
from backend.services.pipeline_service import process_activity_pipeline


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_DB_TESTS"),
    reason="DB integration tests are disabled. Set RUN_DB_TESTS=1 to run.",
)


TEST_USER_ID = "test_pipeline_idempotency_user"
TEST_ACTIVITY_ID = 999000333444
TEST_ATHLETE_ID = 191684548


def _cleanup() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from activity_rpe_resolution where canonical_activity_id = %s;",
                (TEST_ACTIVITY_ID,),
            )
            cur.execute(
                "delete from activity_rpe_observation where canonical_activity_id = %s;",
                (TEST_ACTIVITY_ID,),
            )
            cur.execute(
                "delete from activity_response_metrics where strava_activity_id = %s;",
                (TEST_ACTIVITY_ID,),
            )
            cur.execute(
                "delete from activity_metrics where strava_activity_id = %s;",
                (TEST_ACTIVITY_ID,),
            )
            cur.execute(
                "delete from strava_activity_stream_raw where strava_activity_id = %s;",
                (TEST_ACTIVITY_ID,),
            )
            cur.execute(
                "delete from strava_activity_raw where strava_activity_id = %s;",
                (TEST_ACTIVITY_ID,),
            )
            cur.execute(
                "delete from daily_training_load where user_id = %s;",
                (TEST_USER_ID,),
            )
            cur.execute(
                "delete from daily_fitness_state where user_id = %s;",
                (TEST_USER_ID,),
            )
            cur.execute(
                "delete from user_training_profile where user_id = %s;",
                (TEST_USER_ID,),
            )
            conn.commit()


def _seed_profile() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into user_training_profile (
                    user_id,
                    effective_from,
                    ftp_watts,
                    hr_max,
                    power_z1_upper,
                    power_z2_upper,
                    power_z3_upper,
                    power_z4_upper,
                    power_z5_upper,
                    power_z6_upper,
                    hr_z1_upper,
                    hr_z2_upper,
                    hr_z3_upper,
                    hr_z4_upper
                )
                values (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                );
                """,
                (
                    TEST_USER_ID,
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    200,
                    190,
                    110,
                    150,
                    180,
                    210,
                    240,
                    280,
                    120,
                    140,
                    155,
                    170,
                ),
            )
            conn.commit()


def _fake_activity():
    return {
        "id": TEST_ACTIVITY_ID,
        "sport_type": "VirtualRide",
        "name": "Idempotency Test Workout",
        "start_date": "2026-04-02T18:00:00Z",
        "timezone": "(GMT+00:00) UTC",
        "distance": 20000.0,
        "moving_time": 60,
        "elapsed_time": 60,
        "total_elevation_gain": 100.0,
        "average_speed": 5.0,
        "max_speed": 8.0,
        "average_heartrate": 130.0,
        "max_heartrate": 145.0,
        "average_watts": 150.0,
        "max_watts": 180.0,
        "weighted_average_watts": 150.0,
        "kilojoules": 50.0,
        "trainer": True,
        "commute": False,
        "manual": False,
        "perceived_exertion": 7,
    }


def _fake_streams():
    return {
        "time": {
            "series_type": "time",
            "resolution": "high",
            "original_size": 60,
            "data": list(range(60)),
        },
        "watts": {
            "series_type": "time",
            "resolution": "high",
            "original_size": 60,
            "data": [150] * 60,
        },
        "heartrate": {
            "series_type": "time",
            "resolution": "high",
            "original_size": 60,
            "data": [130] * 60,
        },
    }


@patch("backend.services.pipeline_service.fetch_activity_streams")
@patch("backend.services.pipeline_service.fetch_activity")
@patch("backend.services.pipeline_service.refresh_strava_token_if_needed")
def test_process_activity_pipeline_is_idempotent(
    mock_refresh,
    mock_fetch_activity,
    mock_fetch_streams,
):
    _cleanup()
    _seed_profile()

    try:
        mock_refresh.return_value = ("fake_token", None, None)
        mock_fetch_activity.return_value = _fake_activity()
        mock_fetch_streams.return_value = _fake_streams()

        result1 = process_activity_pipeline(
            user_id=TEST_USER_ID,
            athlete_id=TEST_ATHLETE_ID,
            activity_id=TEST_ACTIVITY_ID,
        )

        result2 = process_activity_pipeline(
            user_id=TEST_USER_ID,
            athlete_id=TEST_ATHLETE_ID,
            activity_id=TEST_ACTIVITY_ID,
        )

        assert result1["ok"] is True
        assert result2["ok"] is True

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select count(*) from strava_activity_raw where strava_activity_id = %s;",
                    (TEST_ACTIVITY_ID,),
                )
                raw_count = cur.fetchone()[0]

                cur.execute(
                    "select count(*) from strava_activity_stream_raw where strava_activity_id = %s;",
                    (TEST_ACTIVITY_ID,),
                )
                streams_count = cur.fetchone()[0]

                cur.execute(
                    """
                    select count(*)
                    from activity_metrics
                    where strava_activity_id = %s
                      and version = 'v1';
                    """,
                    (TEST_ACTIVITY_ID,),
                )
                metrics_count = cur.fetchone()[0]

                cur.execute(
                    """
                    select count(*)
                    from activity_response_metrics
                    where strava_activity_id = %s
                      and version = 'v2_rpe_1_10'
                      and rpe_score = 7;
                    """,
                    (TEST_ACTIVITY_ID,),
                )
                response_count = cur.fetchone()[0]
                cur.execute(
                    """
                    select count(*) from activity_rpe_observation
                    where canonical_activity_id = %s and source = 'strava'
                      and score = 7 and scale_version = 'rpe_1_10';
                    """,
                    (TEST_ACTIVITY_ID,),
                )
                strava_rpe_count = cur.fetchone()[0]

        assert raw_count == 1
        assert streams_count == 3
        assert metrics_count == 1
        assert response_count == 1
        assert strava_rpe_count == 1

    finally:
        _cleanup()
