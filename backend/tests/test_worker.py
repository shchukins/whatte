from datetime import datetime, timezone

from backend import worker


class _FakeDateTime(datetime):
    current = datetime(2026, 5, 15, 7, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current


def test_maybe_schedule_next_day_recovery_prompts_runs_at_configured_hour(monkeypatch):
    calls = []

    monkeypatch.setattr(worker, "datetime", _FakeDateTime)
    monkeypatch.setattr(worker, "NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC", 7)
    monkeypatch.setattr(
        worker,
        "schedule_next_day_recovery_prompts",
        lambda target_date: calls.append(target_date) or {
            "target_date": "2026-05-15",
            "processed_users": 1,
            "sent_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
        },
    )

    worker.maybe_schedule_next_day_recovery_prompts()

    assert calls == [datetime(2026, 5, 15, 7, 0, tzinfo=timezone.utc).date()]


def test_maybe_schedule_next_day_recovery_prompts_skips_outside_configured_hour(monkeypatch):
    calls = []
    _FakeDateTime.current = datetime(2026, 5, 15, 6, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(worker, "datetime", _FakeDateTime)
    monkeypatch.setattr(worker, "NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC", 7)
    monkeypatch.setattr(
        worker,
        "schedule_next_day_recovery_prompts",
        lambda target_date: calls.append(target_date),
    )

    worker.maybe_schedule_next_day_recovery_prompts()

    assert calls == []
