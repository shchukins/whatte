from datetime import date, datetime, timedelta, timezone
import inspect

import pytest

from backend.services import activity_deduplication_service as dedup
from backend.services import fitness_service, load_service, load_state_v2, readiness_daily
from backend.services import notification_service
from backend.services import subjective_feedback_service as feedback


MYWHOOSH_ID = 1001
GARMIN_ID = 1002
START = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)


def _activity(
    activity_id: int,
    *,
    source: str,
    start: datetime = START,
    duration: int = 3600,
    activity_type: str = "VirtualRide",
) -> dict:
    device_name = {
        "mywhoosh": "MyWhoosh",
        "garmin": "Garmin Edge 1050",
        "unknown": "",
    }[source]
    return {
        "strava_activity_id": activity_id,
        "user_id": "user-1",
        "activity_type": activity_type,
        "name": "Indoor training",
        "start_date": start,
        "moving_time_s": duration,
        "elapsed_time_s": duration,
        "trainer": True,
        "raw_json": {
            "sport_type": activity_type,
            "device_name": device_name,
        },
        "deduplication_manual_override": None,
        "duplicate_candidate_activity_id": None,
    }


def test_mywhoosh_first_garmin_later_selects_mywhoosh_canonical():
    result = dedup.evaluate_duplicate_pair(
        _activity(GARMIN_ID, source="garmin", start=START + timedelta(minutes=2)),
        _activity(MYWHOOSH_ID, source="mywhoosh"),
    )

    assert result["decision"] == "auto_merge"
    assert result["canonical_activity_id"] == MYWHOOSH_ID
    assert result["duplicate_activity_id"] == GARMIN_ID
    assert result["confidence"] >= dedup.HIGH_CONFIDENCE_THRESHOLD


def test_garmin_first_mywhoosh_later_switches_canonical_to_mywhoosh():
    result = dedup.evaluate_duplicate_pair(
        _activity(MYWHOOSH_ID, source="mywhoosh"),
        _activity(GARMIN_ID, source="garmin", start=START + timedelta(minutes=2)),
    )

    assert result["decision"] == "auto_merge"
    assert result["canonical_activity_id"] == MYWHOOSH_ID
    assert result["duplicate_activity_id"] == GARMIN_ID


def test_contained_mywhoosh_merges_when_garmin_started_early_and_is_longer():
    mywhoosh = _activity(
        MYWHOOSH_ID,
        source="mywhoosh",
        start=START + timedelta(minutes=26, seconds=20),
        duration=34 * 60 + 20,
    )
    garmin = _activity(
        GARMIN_ID,
        source="garmin",
        start=START,
        duration=60 * 60 + 24,
        activity_type="Ride",
    )

    result = dedup.evaluate_duplicate_pair(mywhoosh, garmin)

    assert result["decision"] == "auto_merge"
    assert result["canonical_activity_id"] == MYWHOOSH_ID
    assert result["duplicate_activity_id"] == GARMIN_ID
    assert "overlap_ratio:0.9922" in result["reasons"]


def test_late_strava_arrival_does_not_affect_actual_time_match():
    garmin = _activity(GARMIN_ID, source="garmin")
    garmin["fetched_at"] = START + timedelta(hours=8)
    mywhoosh = _activity(MYWHOOSH_ID, source="mywhoosh")
    mywhoosh["fetched_at"] = START + timedelta(minutes=1)

    assert dedup.evaluate_duplicate_pair(garmin, mywhoosh)["decision"] == "auto_merge"


def test_two_real_rides_on_same_day_are_not_merged():
    result = dedup.evaluate_duplicate_pair(
        _activity(GARMIN_ID, source="garmin", start=START + timedelta(hours=4)),
        _activity(MYWHOOSH_ID, source="mywhoosh"),
    )

    assert result["decision"] == "no_match"
    assert "overlap_below_threshold" in result["reasons"]


def test_overlap_below_threshold_is_not_merged():
    result = dedup.evaluate_duplicate_pair(
        _activity(GARMIN_ID, source="garmin", start=START + timedelta(minutes=15)),
        _activity(MYWHOOSH_ID, source="mywhoosh"),
    )

    assert result["decision"] == "no_match"
    assert "overlap_below_threshold" in result["reasons"]


def test_manual_separate_override_blocks_repeat_detection():
    garmin = _activity(GARMIN_ID, source="garmin")
    garmin["deduplication_manual_override"] = "separate"
    garmin["duplicate_candidate_activity_id"] = MYWHOOSH_ID

    result = dedup.evaluate_duplicate_pair(
        garmin,
        _activity(MYWHOOSH_ID, source="mywhoosh"),
    )

    assert result["decision"] == "separate"
    assert result["reasons"] == ["manual_separate_override"]


def test_source_uses_metadata_before_name_fallback():
    activity = _activity(MYWHOOSH_ID, source="garmin")
    activity["name"] = "MyWhoosh - misleading copied title"

    assert dedup.identify_activity_source(activity) == {
        "source": "garmin",
        "reason": "device_or_upload_metadata",
    }


def test_virtual_ride_and_trainer_are_a_source_fallback():
    activity = _activity(MYWHOOSH_ID, source="unknown")

    assert dedup.identify_activity_source(activity) == {
        "source": "virtual_ride",
        "reason": "virtual_ride_trainer_fallback",
    }


def test_virtual_ride_fallback_does_not_auto_merge_with_garmin():
    result = dedup.evaluate_duplicate_pair(
        _activity(MYWHOOSH_ID, source="unknown"),
        _activity(GARMIN_ID, source="garmin", activity_type="Ride"),
    )

    assert result["decision"] == "no_match"
    assert "source_pair_not_mywhoosh_garmin" in result["reasons"]


def test_excluded_duplicate_suppresses_notification_and_rpe(monkeypatch):
    monkeypatch.setattr(
        notification_service,
        "get_activity_deduplication_state",
        lambda activity_id: {
            "activity_id": activity_id,
            "canonical_activity_id": MYWHOOSH_ID,
            "user_id": "user-1",
            "is_excluded": True,
            "exclusion_reason": "automatic_duplicate",
        },
    )
    claim_calls = []
    monkeypatch.setattr(
        notification_service,
        "claim_activity_delivery",
        lambda **kwargs: claim_calls.append(kwargs),
    )

    assert (
        notification_service.notify_training_processed("user-1", GARMIN_ID) is False
    )
    assert claim_calls == []


def test_repeat_ingest_delivers_one_notification_and_one_rpe(monkeypatch):
    sent = []
    rpe = []
    claims = iter([True, False])
    monkeypatch.setattr(
        notification_service,
        "get_activity_deduplication_state",
        lambda activity_id: {
            "activity_id": activity_id,
            "canonical_activity_id": MYWHOOSH_ID,
            "user_id": "user-1",
            "is_excluded": False,
            "exclusion_reason": None,
        },
    )
    monkeypatch.setattr(
        notification_service,
        "claim_activity_delivery",
        lambda **kwargs: next(claims),
    )
    monkeypatch.setattr(
        notification_service,
        "build_training_processed_message",
        lambda **kwargs: "processed",
    )
    monkeypatch.setattr(
        notification_service,
        "send_telegram_message",
        lambda text: sent.append(text) or {"result": {"message_id": 1}},
    )
    monkeypatch.setattr(
        notification_service,
        "mark_activity_delivery_sent",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        notification_service,
        "send_post_ride_rpe_request",
        lambda activity_id: rpe.append(activity_id),
    )

    assert notification_service.notify_training_processed("user-1", MYWHOOSH_ID)
    assert not notification_service.notify_training_processed("user-1", MYWHOOSH_ID)
    assert sent == ["processed"]
    assert rpe == [MYWHOOSH_ID]


def test_old_garmin_rpe_callback_is_stored_against_canonical(monkeypatch):
    captured = {}
    monkeypatch.setattr(feedback, "_load_activity_user_id", lambda activity_id: "user-1")
    monkeypatch.setattr(
        feedback,
        "resolve_canonical_activity",
        lambda activity_id: MYWHOOSH_ID,
    )
    monkeypatch.setattr(
        feedback,
        "build_feedback_context_snapshot",
        lambda user_id: {"readiness_score": 50},
    )
    monkeypatch.setattr(
        feedback,
        "upsert_subjective_feedback",
        lambda **kwargs: captured.update(kwargs) or kwargs,
    )
    monkeypatch.setattr(
        feedback,
        "compute_and_store_activity_response",
        lambda activity_id: {"ok": True, "activity_id": activity_id},
    )

    feedback.upsert_activity_subjective_feedback(
        activity_id=GARMIN_ID,
        score=3,
    )

    assert captured["activity_id"] == GARMIN_ID
    assert captured["canonical_activity_id"] == MYWHOOSH_ID
    assert captured["payload"]["source_activity_id"] == GARMIN_ID
    assert captured["payload"]["canonical_activity_id"] == MYWHOOSH_ID


def test_manual_callback_format_round_trip():
    payload = feedback.build_deduplication_callback_data("separate", GARMIN_ID)

    assert payload == f"dedup:separate:{GARMIN_ID}"
    assert feedback.parse_deduplication_callback_data(payload) == {
        "action": "separate",
        "activity_id": GARMIN_ID,
    }


def test_manual_separate_callback_runs_real_state_transition(monkeypatch):
    calls = []
    edits = []
    monkeypatch.setattr(
        feedback,
        "mark_activities_separate",
        lambda activity_id: calls.append(activity_id)
        or {
            "activity_id": activity_id,
            "canonical_activity_id": activity_id,
            "user_id": "user-1",
            "is_excluded": False,
            "exclusion_reason": None,
        },
    )
    monkeypatch.setattr(
        feedback,
        "answer_telegram_callback",
        lambda callback_query_id, text=None: None,
    )
    monkeypatch.setattr(
        feedback,
        "edit_telegram_message",
        lambda chat_id, message_id, text: edits.append((chat_id, message_id, text)),
    )

    result = feedback.handle_telegram_feedback_callback(
        {
            "callback_query": {
                "id": "cb-1",
                "data": f"dedup:separate:{GARMIN_ID}",
                "message": {"message_id": 9, "chat": {"id": 7}},
            }
        }
    )

    assert result["ok"] is True
    assert calls == [GARMIN_ID]
    assert edits[0][0:2] == (7, 9)
    assert "учитывается отдельно" in edits[0][2]


def test_resolve_canonical_activity_rejects_cycle(monkeypatch):
    class Cursor:
        links = {MYWHOOSH_ID: GARMIN_ID, GARMIN_ID: MYWHOOSH_ID}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params):
            self.activity_id = params[0]

        def fetchone(self):
            return (self.links[self.activity_id], None)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(dedup, "get_conn", lambda: Conn())

    with pytest.raises(ValueError, match="duplicate cycle detected"):
        dedup.resolve_canonical_activity(MYWHOOSH_ID)


def test_user_visible_telegram_builders_do_not_contain_legacy_brand():
    assert "Human Engine" not in inspect.getsource(notification_service)
    assert "Human Engine" not in inspect.getsource(feedback)


def test_activity_recompute_creates_readiness_from_load_state_dates(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchall(self):
            return [(date(2026, 8, 29),), (date(2026, 8, 30),)]

    class Conn:
        def __init__(self):
            self.cursor_instance = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return self.cursor_instance

    conn = Conn()
    recomputed = []
    monkeypatch.setattr(load_service, "recompute_daily_load_all", lambda user_id: {"ok": True})
    monkeypatch.setattr(fitness_service, "recompute_fitness_state", lambda user_id: {"ok": True})
    monkeypatch.setattr(load_state_v2, "recompute_load_state_daily_v2", lambda user_id: {"ok": True})
    monkeypatch.setattr(
        readiness_daily,
        "recompute_readiness_daily_for_date",
        lambda user_id, target_date: recomputed.append((user_id, target_date)),
    )
    monkeypatch.setattr(dedup, "get_conn", lambda: conn)

    result = dedup.recompute_after_activity_state_change("user-1", date(2026, 8, 29))

    assert "from load_state_daily_v2" in conn.cursor_instance.query
    assert conn.cursor_instance.params == ("user-1", date(2026, 8, 29))
    assert recomputed == [
        ("user-1", "2026-08-29"),
        ("user-1", "2026-08-30"),
    ]
    assert result["readiness_dates"] == ["2026-08-29", "2026-08-30"]
