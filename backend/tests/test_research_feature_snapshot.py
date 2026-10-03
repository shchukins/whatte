from datetime import date, datetime, timezone

from backend.services import research_feature_snapshot


class _Cursor:
    def __init__(self):
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _query, params):
        self.params = params

    def fetchone(self):
        return (19, datetime(2026, 9, 1, 6, tzinfo=timezone.utc))


class _Connection:
    def __init__(self):
        self.cursor_value = _Cursor()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True


def test_capture_persists_the_exact_cutoff_vector(monkeypatch):
    cutoff = datetime(2026, 9, 1, 5, tzinfo=timezone.utc)
    vector = {
        "feature_vector_version": "daily_feature_vector_v1",
        "cutoff_at": cutoff.isoformat(),
        "features": {"load.tss": {"value": None, "availability": "unavailable", "reason_codes": []}},
    }
    connection = _Connection()
    monkeypatch.setattr(research_feature_snapshot, "get_conn", lambda: connection)
    monkeypatch.setattr(
        research_feature_snapshot, "build_daily_feature_vector", lambda **kwargs: vector,
    )

    result = research_feature_snapshot.capture_research_feature_snapshot(
        user_id="u", local_date=date(2026, 9, 1), reference_key="delivery:u:2026-09-01",
        cutoff_at=cutoff,
    )

    assert result["id"] == 19
    assert result["feature_vector"] == vector
    assert connection.committed is True
    assert connection.cursor_value.params[5] == cutoff
    assert connection.cursor_value.params[4] == "daily_feature_vector_v1"
