from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.today import history_service as diary
from backend.today import service as today


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.calls.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.rows

    def cursor(self):
        return self


@pytest.mark.parametrize("target,tz,hours", [
    (date(2026, 8, 30), "Europe/Moscow", 336),
    (date(2026, 3, 29), "Europe/Berlin", 335),
    (date(2026, 10, 25), "Europe/Berlin", 337),
])
def test_activity_query_uses_local_midnights_and_one_read(monkeypatch, target, tz, hours):
    cursor = Cursor([])
    monkeypatch.setattr(diary, "get_conn", lambda: cursor)
    monkeypatch.setattr(diary, "WHATTE_TZ", ZoneInfo(tz))
    assert diary.get_diary_activities("athlete", target) == []
    assert len(cursor.calls) == 1
    query, (user, start, end) = cursor.calls[0]
    assert user == "athlete"
    assert start.date() == target - timedelta(days=13)
    assert end.date() == target + timedelta(days=1)
    assert start.hour == end.hour == 0
    assert (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() == hours * 3600
    for clause in ("r.user_id = %s", "r.is_deleted = false", "r.is_excluded = false",
                   "r.duplicate_of_activity_id is null", "r.start_date >= %s", "r.start_date < %s"):
        assert clause in query
    assert "limit" not in query.lower()


def test_diary_keeps_multiple_workouts_null_zero_and_persisted_rpe(monkeypatch):
    target = date(2026, 8, 30)
    cursor = Cursor([
        (3, "Late", "Ride", datetime(2026, 8, 29, 22, tzinfo=timezone.utc),
         0, 4, "web", True, 4, 8, 7),
        (2, "Earlier", "Run", datetime(2026, 8, 29, 21, tzinfo=timezone.utc),
         None, None, None, None, 5, None, None),
        (1, "Previous", "Ride", datetime(2026, 8, 29, 20, 59, tzinfo=timezone.utc),
         3600, 7, "telegram", False, None, None, 7),
    ])
    monkeypatch.setattr(diary, "get_conn", lambda: cursor)
    monkeypatch.setattr(diary, "WHATTE_TZ", ZoneInfo("Europe/Moscow"))
    version = today.READINESS_MODEL_VERSION
    monkeypatch.setattr(today, "get_readiness_daily_calendar_history", lambda *args: [
        {"date": target, "version": version, "readiness_score": 68, "recommendation": "moderate"},
        {"date": target, "version": "old", "readiness_score": 65, "recommendation": None},
    ])
    monkeypatch.setattr(today, "_get_recovery_history", lambda *args: {target: (4, "fresh")})
    result = diary.get_diary_data("athlete", target)
    assert [day.date for day in result.days] == [
        (target - timedelta(days=n)).isoformat() for n in range(14)
    ]
    assert [a.activity_id for a in result.days[0].activities] == [3, 2]
    assert [a.activity_id for a in result.days[1].activities] == [1]
    first, second = result.days[0].activities
    assert first.start_time.isoformat() == "2026-08-30T01:00:00+03:00"
    assert first.duration_s == 0
    assert (first.rpe_score, first.rpe_source) == (4, "web")
    assert (first.rpe_web_score, first.rpe_strava_score, first.rpe_telegram_score) == (4, 8, 7)
    assert first.rpe_disagreement is True
    assert second.duration_s is None
    # A Web observation never invents a missing effective resolution.
    assert second.rpe_score is second.rpe_source is None
    assert second.rpe_web_score == 5
    assert result.days[0].activity_message is None
    assert result.days[2].activity_message == "Нет записанных тренировок"
    assert result.history_groups[0].rows[0].recovery_score == 4
    assert result.history_groups[0].rows[0].recommendation == "moderate"
    assert result.history_groups[1].supported is False
    assert result.history_groups[1].rows[0].recommendation is None


@pytest.mark.parametrize("failed", ["activities", "history", "both", None])
def test_diary_sections_fail_independently_and_keep_all_days(monkeypatch, failed):
    def activities(*args):
        if failed in ("activities", "both"):
            raise RuntimeError("activity unavailable" + "x" * 300)
        return []

    def history(*args):
        if failed in ("history", "both"):
            raise RuntimeError("history unavailable")
        return [today.TodayHistoryGroup("current", True, [])]

    monkeypatch.setattr(diary, "get_diary_activities", activities)
    monkeypatch.setattr(diary, "get_today_history", history)
    result = diary.get_diary_data("athlete", date(2026, 8, 30))
    assert len(result.days) == 14
    if failed in ("activities", "both"):
        assert result.activity_section.status == "error"
        assert len(result.activity_section.error) == today.MAX_SECTION_ERROR_LENGTH
        assert all(d.activities is None for d in result.days)
        assert result.days[0].activity_message == "Не удалось загрузить тренировки"
    else:
        assert result.activity_section.status == "ok"
        assert all(d.activities == [] for d in result.days)
        assert result.days[0].activity_message == "Нет записанных тренировок"
    if failed in ("history", "both"):
        assert result.history_section.status == "error"
        assert result.history_groups == []
    else:
        assert result.history_section.status == "ok"
        assert len(result.history_groups) == 1
