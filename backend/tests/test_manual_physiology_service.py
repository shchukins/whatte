from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from backend.services import manual_physiology_service as physiology


NOW = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)


def observation(**overrides):
    values = {
        "id": 7,
        "user_id": "user-1",
        "local_date": date(2026, 9, 30),
        "sleep_duration_minutes": 450,
        "sleep_quality": 4,
        "hrv_ms": 58.0,
        "resting_hr_bpm": 49.0,
        "source": "telegram",
        "observed_at": NOW,
        "schema_version": physiology.MANUAL_PHYSIOLOGY_SCHEMA_VERSION,
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return physiology.ManualPhysiologyObservation(**values)


def row(value):
    return tuple(value.model_dump().values())


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(physiology, "local_today", lambda: date(2026, 9, 30))


@pytest.mark.parametrize(
    "field,value",
    [
        ("sleep_duration_minutes", -1),
        ("sleep_duration_minutes", 1441),
        ("sleep_quality", 0),
        ("sleep_quality", 6),
        ("hrv_ms", 0),
        ("hrv_ms", 501),
        ("resting_hr_bpm", 19),
        ("resting_hr_bpm", 251),
        ("hrv_ms", float("nan")),
        ("resting_hr_bpm", float("inf")),
    ],
)
def test_rejects_values_outside_storage_sanity_ranges(field, value):
    with pytest.raises(ValidationError):
        physiology.ManualPhysiologyPatch(
            local_date=date(2026, 9, 30), source="web", **{field: value}
        )


def test_rejects_unknown_source():
    with pytest.raises(ValidationError):
        physiology.ManualPhysiologyPatch(
            local_date=date(2026, 9, 30), source="healthkit"
        )


def test_rejects_future_local_date_and_naive_observed_at():
    with pytest.raises(ValidationError, match="Future local dates"):
        physiology.ManualPhysiologyPatch(
            local_date=date(2026, 10, 1), source="web"
        )
    with pytest.raises(ValidationError, match="include a timezone"):
        physiology.ManualPhysiologyPatch(
            local_date=date(2026, 9, 30),
            source="web",
            observed_at=datetime(2026, 9, 30, 8),
        )


def test_local_today_uses_configured_timezone_boundary(monkeypatch):
    monkeypatch.undo()
    instant = datetime(2026, 9, 29, 21, 30, tzinfo=timezone.utc)
    assert physiology.local_today(now=instant, timezone="Europe/Moscow") == date(
        2026, 9, 30
    )
    assert physiology.local_today(now=instant, timezone="America/New_York") == date(
        2026, 9, 29
    )


def test_partial_edit_preserves_omitted_fields_and_explicit_null_clears():
    current = observation()
    patch = physiology.ManualPhysiologyPatch(
        local_date=current.local_date,
        source="web",
        hrv_ms=None,
        sleep_quality=5,
    )
    values, changed = physiology._merge_patch(current, patch)
    assert values == {
        "sleep_duration_minutes": 450,
        "sleep_quality": 5,
        "hrv_ms": None,
        "resting_hr_bpm": 49.0,
        "observed_at": NOW,
        "source": "web",
    }
    assert changed == ["sleep_quality", "hrv_ms", "source"]


class Cursor:
    def __init__(self, current=None, saved=None):
        self.current = row(current) if current else None
        self.saved = row(saved) if saved else None
        self.fetchone_values = []
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "from manual_physiology_observation" in sql and "for update" in sql:
            self.fetchone_values.append(self.current)
        elif "returning" in sql:
            self.fetchone_values.append(self.saved)

    def fetchone(self):
        return self.fetchone_values.pop(0)


class Connection:
    def __init__(self, cursor):
        self.cursor_value = cursor
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1


def test_create_persists_current_row_and_first_revision(monkeypatch):
    saved = observation(
        sleep_quality=None,
        hrv_ms=None,
        resting_hr_bpm=None,
        observed_at=None,
    )
    cursor = Cursor(saved=saved)
    conn = Connection(cursor)
    monkeypatch.setattr(physiology, "get_conn", lambda: conn)
    patch = physiology.ManualPhysiologyPatch(
        local_date=date(2026, 9, 30),
        source="telegram",
        sleep_duration_minutes=450,
    )

    result = physiology.save_manual_physiology_observation(
        user_id="user-1", patch=patch
    )

    assert result.changed
    assert result.changed_fields == ["sleep_duration_minutes", "source"]
    assert result.observation.revision == 1
    assert any(
        "insert into manual_physiology_observation_revision" in sql
        for sql, _ in cursor.calls
    )
    assert conn.commits == 1


def test_repeat_submission_is_idempotent(monkeypatch):
    current = observation()
    cursor = Cursor(current=current)
    conn = Connection(cursor)
    monkeypatch.setattr(physiology, "get_conn", lambda: conn)
    patch = physiology.ManualPhysiologyPatch(
        local_date=current.local_date,
        source=current.source,
        sleep_duration_minutes=current.sleep_duration_minutes,
        sleep_quality=current.sleep_quality,
        hrv_ms=current.hrv_ms,
        resting_hr_bpm=current.resting_hr_bpm,
        observed_at=current.observed_at,
    )

    result = physiology.save_manual_physiology_observation(
        user_id=current.user_id, patch=patch
    )

    assert not result.changed
    assert result.observation.revision == 1
    assert not any("_revision" in sql for sql, _ in cursor.calls)
    assert conn.commits == 1


def test_edit_increments_revision_and_records_changed_fields(monkeypatch):
    current = observation()
    saved = observation(
        sleep_quality=3,
        source="web",
        revision=2,
        updated_at=datetime(2026, 9, 30, 9, tzinfo=timezone.utc),
    )
    cursor = Cursor(current=current, saved=saved)
    conn = Connection(cursor)
    monkeypatch.setattr(physiology, "get_conn", lambda: conn)
    patch = physiology.ManualPhysiologyPatch(
        local_date=current.local_date,
        source="web",
        sleep_quality=3,
    )

    result = physiology.save_manual_physiology_observation(
        user_id=current.user_id, patch=patch
    )

    assert result.changed_fields == ["sleep_quality", "source"]
    assert result.observation.revision == 2
    revision_params = next(
        params for sql, params in cursor.calls
        if "insert into manual_physiology_observation_revision" in sql
    )
    assert revision_params[-2] == ["sleep_quality", "source"]


def test_empty_user_id_is_rejected_before_database_access():
    patch = physiology.ManualPhysiologyPatch(
        local_date=date(2026, 9, 30), source="web"
    )
    with pytest.raises(ValueError, match="user_id"):
        physiology.save_manual_physiology_observation(user_id=" ", patch=patch)
