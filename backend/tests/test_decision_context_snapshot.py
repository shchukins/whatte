from datetime import date, datetime, timezone

from backend.services import decision_context_snapshot


class _Cursor:
    def __init__(self, readiness_row):
        self.readiness_row = readiness_row
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.calls += 1

    def fetchone(self):
        if self.calls == 1:
            return self.readiness_row
        return None


class _Connection:
    def __init__(self, readiness_row):
        self.cursor_value = _Cursor(readiness_row)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        pass


def test_snapshot_fingerprint_ignores_recompute_time(monkeypatch):
    explanation = {"signal_families": {"freshness": {"used": True}}}
    rows = iter([
        (70.0, 0.7, "Good", explanation,
         datetime(2026, 9, 1, 5, tzinfo=timezone.utc)),
        (70.0, 0.7, "Good", explanation,
         datetime(2026, 9, 1, 6, tzinfo=timezone.utc)),
    ])
    monkeypatch.setattr(
        decision_context_snapshot,
        "get_conn",
        lambda: _Connection(next(rows)),
    )

    first = decision_context_snapshot.capture_decision_context_snapshot(
        user_id="user-1",
        snapshot_date=date(2026, 9, 1),
        event_type="recovery_checkin_after",
        reference_key="checkin-1",
    )
    second = decision_context_snapshot.capture_decision_context_snapshot(
        user_id="user-1",
        snapshot_date=date(2026, 9, 1),
        event_type="recovery_checkin_after",
        reference_key="checkin-1",
    )

    assert first["readiness_computed_at"] != second["readiness_computed_at"]
    assert first["content_fingerprint"] == second["content_fingerprint"]


def test_snapshot_includes_event_context_in_immutable_state(monkeypatch):
    monkeypatch.setattr(
        decision_context_snapshot,
        "get_conn",
        lambda: _Connection((70.0, 0.7, "Good", {}, datetime(2026, 9, 1, 5, tzinfo=timezone.utc))),
    )

    result = decision_context_snapshot.capture_decision_context_snapshot(
        user_id="user-1", snapshot_date=date(2026, 9, 1),
        event_type="post_activity_state", reference_key="post_activity:user-1:7",
        event_context={"canonical_activity_id": 7},
    )

    assert result["event_context"] == {"canonical_activity_id": 7}
