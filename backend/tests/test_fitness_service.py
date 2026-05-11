from backend.services import fitness_service


class _FakeCursor:
    def __init__(self, rows) -> None:
        self._rows = rows
        self.executed: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def test_recompute_fitness_state_returns_empty_when_no_supported_load(monkeypatch):
    fake_cursor = _FakeCursor([])
    fake_conn = _FakeConn(fake_cursor)

    monkeypatch.setattr(fitness_service, "get_conn", lambda: fake_conn)

    result = fitness_service.recompute_fitness_state(user_id="user-1")

    assert result == {
        "ok": True,
        "user_id": "user-1",
        "days_processed": 0,
        "last_date": None,
        "last_daily_tss": None,
        "last_fitness_signal": None,
        "last_fatigue_signal": None,
        "last_freshness_signal": None,
    }
    assert any("delete from daily_fitness_state" in query for query, _ in fake_cursor.executed)
    assert fake_conn.committed is True
