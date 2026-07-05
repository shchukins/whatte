from backend.services import load_service


class _FakeCursor:
    def __init__(self, rows) -> None:
        self._rows = rows
        self.executed: list[tuple[str, tuple | None]] = []
        self.insert_params: list[tuple] = []
        self.deleted = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "delete from daily_training_load" in query:
            self.deleted = True
        if "insert into daily_training_load" in query:
            self.insert_params.append(params)

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


def test_recompute_daily_load_all_excludes_unsupported_activity(monkeypatch):
    fake_cursor = _FakeCursor(
        [
            (
                "user-1",
                "2026-04-17",
                "TableTennis",
                3600,
                0.0,
                0.0,
                0.0,
                None,
                None,
                None,
            )
        ]
    )
    fake_conn = _FakeConn(fake_cursor)

    monkeypatch.setattr(load_service, "get_conn", lambda: fake_conn)

    result = load_service.recompute_daily_load_all(user_id="user-1")

    assert result == {
        "ok": True,
        "user_id": "user-1",
        "days_processed": 0,
        "from_date": None,
        "to_date": None,
    }
    assert fake_cursor.deleted is True
    assert fake_cursor.insert_params == []
    assert fake_conn.committed is True


def test_recompute_daily_load_all_keeps_supported_cycling_activity(monkeypatch):
    fake_cursor = _FakeCursor(
        [
            (
                "user-1",
                "2026-04-17",
                "Ride",
                5400,
                45000.0,
                500.0,
                900.0,
                72.5,
                210.0,
                0.84,
            )
        ]
    )
    fake_conn = _FakeConn(fake_cursor)

    monkeypatch.setattr(load_service, "get_conn", lambda: fake_conn)

    result = load_service.recompute_daily_load_all(user_id="user-1")

    assert result == {
        "ok": True,
        "user_id": "user-1",
        "days_processed": 1,
        "from_date": "2026-04-17",
        "to_date": "2026-04-17",
    }
    assert fake_cursor.deleted is True
    assert fake_cursor.insert_params == [
        ("user-1", "2026-04-17", 1, 5400.0, 45000.0, 500.0, 900.0, 72.5)
    ]
    assert fake_conn.committed is True


def test_recompute_daily_load_all_counts_only_supported_load_activities(monkeypatch):
    fake_cursor = _FakeCursor(
        [
            (
                "user-1",
                "2026-04-17",
                "Ride",
                5400,
                45000.0,
                500.0,
                900.0,
                72.5,
                210.0,
                0.84,
            ),
            (
                "user-1",
                "2026-04-17",
                "TableTennis",
                3600,
                0.0,
                0.0,
                0.0,
                None,
                None,
                None,
            ),
        ]
    )
    fake_conn = _FakeConn(fake_cursor)

    monkeypatch.setattr(load_service, "get_conn", lambda: fake_conn)

    result = load_service.recompute_daily_load_all(user_id="user-1")

    assert result == {
        "ok": True,
        "user_id": "user-1",
        "days_processed": 1,
        "from_date": "2026-04-17",
        "to_date": "2026-04-17",
    }
    assert fake_cursor.deleted is True
    assert fake_cursor.insert_params == [
        ("user-1", "2026-04-17", 1, 5400.0, 45000.0, 500.0, 900.0, 72.5)
    ]
    assert fake_conn.committed is True
