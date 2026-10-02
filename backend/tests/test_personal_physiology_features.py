from datetime import date, datetime, timedelta, timezone

import pytest

from backend.services import personal_physiology_features as features


TARGET_DATE = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 6, tzinfo=timezone.utc)


def observation(**overrides):
    result = {
        "id": 11,
        "user_id": "sergey",
        "local_date": TARGET_DATE,
        "sleep_duration_minutes": 420,
        "hrv_ms": 60.0,
        "resting_hr_bpm": 50.0,
        "observed_at": NOW,
        "revision": 2,
        "updated_at": NOW,
    }
    result.update(overrides)
    return result


def history(days=7, **overrides):
    rows = []
    for offset in range(days, 0, -1):
        row = {
            "local_date": TARGET_DATE - timedelta(days=offset),
            "sleep_duration_minutes": 480,
            "hrv_ms": 50.0,
            "resting_hr_bpm": 48.0,
        }
        row.update(overrides)
        rows.append(row)
    return rows


def test_builds_mature_personal_relative_features_from_past_days_only():
    result = features.build_personal_physiology_features(
        local_date=TARGET_DATE, observation=observation(), history=history(),
        timezone="Europe/Moscow",
    )

    assert result["feature_version"] == "personal_physiology_features_v1"
    assert result["source_staleness"] == "current_local_date"
    assert result["hrv"] == {
        "observation_count": 7, "availability": "available",
        "baseline_state": "mature", "baseline": 50.0,
        "ratio": 1.2, "deviation": 0.2,
    }
    assert result["resting_hr"]["delta"] == 2.0
    assert result["sleep_duration"] == {
        "observation_count": 7, "availability": "available",
        "baseline_state": "mature", "baseline": 480.0,
        "deviation": -60.0, "debt": 60.0,
    }


def test_missing_target_value_is_unavailable_and_never_imputed():
    result = features.build_personal_physiology_features(
        local_date=TARGET_DATE, observation=observation(hrv_ms=None), history=history(),
    )

    assert result["hrv"] == {
        "observation_count": 7, "availability": "unavailable",
        "baseline_state": "unavailable", "baseline": 50.0,
        "ratio": None, "deviation": None,
    }


def test_insufficient_and_missing_history_remain_explicit():
    result = features.build_personal_physiology_features(
        local_date=TARGET_DATE, observation=observation(), history=history(days=6),
    )

    assert result["hrv"]["baseline_state"] == "immature"
    assert result["hrv"]["baseline"] is None
    assert result["hrv"]["ratio"] is None


def test_median_resists_a_single_outlier_and_missing_calendar_days():
    rows = history()
    rows[0]["hrv_ms"] = 500.0
    rows[2]["local_date"] = date(2026, 9, 10)
    result = features.build_personal_physiology_features(
        local_date=TARGET_DATE, observation=observation(), history=rows,
    )

    assert result["hrv"]["baseline"] == 50.0


def test_rejects_target_or_future_dates_in_baseline_history():
    with pytest.raises(ValueError, match="preceding baseline window"):
        features.build_personal_physiology_features(
            local_date=TARGET_DATE, observation=observation(),
            history=history() + [{
                "local_date": TARGET_DATE, "sleep_duration_minutes": 480,
                "hrv_ms": 50.0, "resting_hr_bpm": 48.0,
            }],
        )


def test_rejects_history_outside_the_configured_calendar_window():
    with pytest.raises(ValueError, match="preceding baseline window"):
        features.build_personal_physiology_features(
            local_date=TARGET_DATE,
            observation=observation(),
            history=[{
                "local_date": date(2026, 9, 2), "sleep_duration_minutes": 480,
                "hrv_ms": 50.0, "resting_hr_bpm": 48.0,
            }],
        )


@pytest.mark.parametrize(
    ("observed_at", "expected"),
    [
        (None, "unknown"),
        (datetime(2026, 9, 30, 6, tzinfo=timezone.utc), "stale"),
        (datetime(2026, 10, 2, 6, tzinfo=timezone.utc), "late"),
    ],
)
def test_source_staleness_is_explicit_and_does_not_change_values(observed_at, expected):
    result = features.build_personal_physiology_features(
        local_date=TARGET_DATE, observation=observation(observed_at=observed_at),
        history=history(), timezone="UTC",
    )

    assert result["source_staleness"] == expected
    assert result["hrv"]["ratio"] == 1.2


class Cursor:
    def __init__(self, current, prior):
        self.current = current
        self.prior = prior
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.prior


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


def test_recompute_uses_manual_observations_and_persists_full_feature_contract(monkeypatch):
    current = (11, "sergey", TARGET_DATE, 420, 60.0, 50.0, NOW, 2, NOW)
    prior = [
        (
            row["local_date"], row["sleep_duration_minutes"], row["hrv_ms"],
            row["resting_hr_bpm"],
        )
        for row in history()
    ]
    cursor = Cursor(current, prior)
    connection = Connection(cursor)
    monkeypatch.setattr(features, "get_conn", lambda: connection)

    result = features.recompute_personal_physiology_features_for_date(
        user_id="sergey", local_date=TARGET_DATE,
    )

    assert result is not None
    assert connection.commits == 1
    history_query, history_params = cursor.calls[1]
    assert "manual_physiology_observation" in history_query
    assert "local_date < %s" in history_query
    assert history_params[-1] == features.BASELINE_WINDOW_DAYS
    assert "personal_physiology_feature_daily" in cursor.calls[2][0]


def test_recompute_returns_none_without_target_day_observation(monkeypatch):
    cursor = Cursor(None, [])
    connection = Connection(cursor)
    monkeypatch.setattr(features, "get_conn", lambda: connection)

    assert features.recompute_personal_physiology_features_for_date(
        user_id="sergey", local_date=TARGET_DATE,
    ) is None
    assert connection.commits == 0
