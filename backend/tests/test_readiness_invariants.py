import json
import math
from datetime import date

from backend.services import health_recovery_daily, load_state_v2, readiness_daily, readiness_query


class _FakeReadinessCursor:
    def __init__(self, load_row, recovery_row) -> None:
        self._load_row = load_row
        self._recovery_row = recovery_row
        self._last_query = ""
        self.insert_params: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self._last_query = query
        if "insert into readiness_daily" in query:
            self.insert_params.append(params)

    def fetchone(self):
        if "from load_state_daily_v2" in self._last_query:
            return self._load_row
        if "from health_recovery_daily" in self._last_query:
            return self._recovery_row
        return None


class _FakeLoadStateCursor:
    def __init__(self, rows) -> None:
        self._rows = rows
        self.insert_params: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        if "insert into load_state_daily_v2" in query:
            self.insert_params.append(params)

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cursor) -> None:
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


class _FakeRecoveryCursor:
    def __init__(
        self,
        *,
        sleep_row,
        resting_hr_row,
        hrv_row,
        weight_row,
        hrv_baseline_row,
        rhr_baseline_row,
    ) -> None:
        self._sleep_row = sleep_row
        self._resting_hr_row = resting_hr_row
        self._hrv_row = hrv_row
        self._weight_row = weight_row
        self._hrv_baseline_row = hrv_baseline_row
        self._rhr_baseline_row = rhr_baseline_row
        self._last_query = ""
        self.insert_params: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self._last_query = query
        if "insert into health_recovery_daily" in query:
            self.insert_params.append(params)

    def fetchone(self):
        if "from health_sleep_night" in self._last_query:
            return self._sleep_row
        if "from health_resting_hr_daily" in self._last_query and "date = %s" in self._last_query:
            return self._resting_hr_row
        if "from health_hrv_sample" in self._last_query and "sample_start_at::date = %s" in self._last_query:
            return self._hrv_row
        if "from health_weight_measurement" in self._last_query:
            return self._weight_row
        if "from health_hrv_sample" in self._last_query and "sample_start_at::date < %s::date" in self._last_query:
            return self._hrv_baseline_row
        if "from health_resting_hr_daily" in self._last_query and "date < %s::date" in self._last_query:
            return self._rhr_baseline_row
        return None


def _build_readiness_result(
    monkeypatch,
    *,
    load_row,
    recovery_row,
):
    fake_cursor = _FakeReadinessCursor(load_row=load_row, recovery_row=recovery_row)
    fake_conn = _FakeConn(fake_cursor)
    monkeypatch.setattr(readiness_daily, "get_conn", lambda: fake_conn)

    result = readiness_daily.recompute_readiness_daily_for_date(
        user_id="user-1",
        target_date="2026-04-16",
    )
    explanation_json = json.loads(fake_cursor.insert_params[0][8])
    return result, explanation_json


def _run_load_state(monkeypatch, tss_values: list[float]):
    rows = [
        (date(2026, 4, 14 + idx), tss)
        for idx, tss in enumerate(tss_values)
    ]
    fake_cursor = _FakeLoadStateCursor(rows)
    fake_conn = _FakeConn(fake_cursor)
    monkeypatch.setattr(load_state_v2, "get_conn", lambda: fake_conn)

    result = load_state_v2.recompute_load_state_daily_v2(user_id="user-1")
    last_insert = fake_cursor.insert_params[-1]
    return {
        "result": result,
        "fatigue_total": last_insert[7],
        "freshness": last_insert[8],
    }


def _run_recovery_daily(
    monkeypatch,
    *,
    sleep_row,
    resting_hr_row,
    hrv_row,
    weight_row,
    hrv_baseline_row,
    rhr_baseline_row,
):
    fake_cursor = _FakeRecoveryCursor(
        sleep_row=sleep_row,
        resting_hr_row=resting_hr_row,
        hrv_row=hrv_row,
        weight_row=weight_row,
        hrv_baseline_row=hrv_baseline_row,
        rhr_baseline_row=rhr_baseline_row,
    )
    fake_conn = _FakeConn(fake_cursor)
    monkeypatch.setattr(health_recovery_daily, "get_conn", lambda: fake_conn)

    result = health_recovery_daily.recompute_health_recovery_daily_for_date(
        user_id="user-1",
        target_date="2026-04-16",
    )
    explanation_json = json.loads(fake_cursor.insert_params[0][10])
    return result, explanation_json, fake_conn


def test_higher_recent_load_increases_fatigue_and_reduces_freshness(monkeypatch):
    lower_load = _run_load_state(monkeypatch, [0.0, 0.0, 50.0])
    higher_load = _run_load_state(monkeypatch, [0.0, 0.0, 100.0])

    assert higher_load["fatigue_total"] > lower_load["fatigue_total"]
    assert higher_load["freshness"] < lower_load["freshness"]
    assert higher_load["result"]["last_freshness"] == higher_load["freshness"]


def test_high_acute_load_reduces_readiness_for_same_recovery(monkeypatch):
    # This guards the product meaning of readiness: more acute strain should
    # not look better when recovery evidence is held constant.
    lower_load = _run_load_state(monkeypatch, [0.0, 0.0, 40.0])
    higher_load = _run_load_state(monkeypatch, [0.0, 0.0, 140.0])

    lower_readiness, _ = _build_readiness_result(
        monkeypatch,
        load_row=(lower_load["freshness"],),
        recovery_row=(70.0, {"sleep_minutes": 480.0, "hrv_today": 58.0, "rhr_today": 49.0}),
    )
    higher_readiness, _ = _build_readiness_result(
        monkeypatch,
        load_row=(higher_load["freshness"],),
        recovery_row=(70.0, {"sleep_minutes": 480.0, "hrv_today": 58.0, "rhr_today": 49.0}),
    )

    assert higher_readiness["readiness_score"] < lower_readiness["readiness_score"]


def test_better_recovery_increases_readiness_for_same_freshness(monkeypatch):
    lower_recovery, _ = _build_readiness_result(
        monkeypatch,
        load_row=(5.0,),
        recovery_row=(45.0, {"sleep_minutes": 360.0, "hrv_today": 42.0, "rhr_today": 58.0}),
    )
    higher_recovery, _ = _build_readiness_result(
        monkeypatch,
        load_row=(5.0,),
        recovery_row=(75.0, {"sleep_minutes": 510.0, "hrv_today": 60.0, "rhr_today": 48.0}),
    )

    assert higher_recovery["readiness_score"] > lower_recovery["readiness_score"]


def test_higher_freshness_does_not_reduce_readiness_for_same_recovery(monkeypatch):
    lower_freshness, _ = _build_readiness_result(
        monkeypatch,
        load_row=(-8.0,),
        recovery_row=(68.0, {"sleep_minutes": 470.0, "hrv_today": 55.0, "rhr_today": 50.0}),
    )
    higher_freshness, _ = _build_readiness_result(
        monkeypatch,
        load_row=(8.0,),
        recovery_row=(68.0, {"sleep_minutes": 470.0, "hrv_today": 55.0, "rhr_today": 50.0}),
    )

    assert higher_freshness["readiness_score"] >= lower_freshness["readiness_score"]


def test_readiness_is_deterministic_for_same_snapshot(monkeypatch):
    first_result, first_explanation = _build_readiness_result(
        monkeypatch,
        load_row=(3.5,),
        recovery_row=(64.0, {"sleep_minutes": 450.0, "hrv_today": 54.0, "rhr_today": 49.0}),
    )
    second_result, second_explanation = _build_readiness_result(
        monkeypatch,
        load_row=(3.5,),
        recovery_row=(64.0, {"sleep_minutes": 450.0, "hrv_today": 54.0, "rhr_today": 49.0}),
    )

    assert second_result["readiness_score"] == first_result["readiness_score"]
    assert second_result["good_day_probability"] == first_result["good_day_probability"]
    assert second_result["status_text"] == first_result["status_text"]
    assert second_explanation == first_explanation


def test_readiness_score_stays_within_bounds_for_extreme_inputs(monkeypatch):
    very_low, _ = _build_readiness_result(
        monkeypatch,
        load_row=(-500.0,),
        recovery_row=(-20.0, {"sleep_minutes": 0.0, "hrv_today": 1.0, "rhr_today": 200.0}),
    )
    very_high, _ = _build_readiness_result(
        monkeypatch,
        load_row=(500.0,),
        recovery_row=(180.0, {"sleep_minutes": 1000.0, "hrv_today": 200.0, "rhr_today": 30.0}),
    )

    assert very_low["readiness_score"] == 0.0
    assert very_low["good_day_probability"] == 0.0
    assert very_high["readiness_score"] == 100.0
    assert very_high["good_day_probability"] == 1.0


def test_recovery_score_improves_with_better_inputs_and_stays_bounded():
    poor_score, poor_explanation = health_recovery_daily._compute_recovery_score_with_baseline(
        sleep_minutes=300.0,
        hrv_today=35.0,
        rhr_today=70.0,
        hrv_baseline=50.0,
        rhr_baseline=50.0,
    )
    good_score, good_explanation = health_recovery_daily._compute_recovery_score_with_baseline(
        sleep_minutes=510.0,
        hrv_today=65.0,
        rhr_today=45.0,
        hrv_baseline=50.0,
        rhr_baseline=50.0,
    )
    extreme_score, _ = health_recovery_daily._compute_recovery_score_with_baseline(
        sleep_minutes=2000.0,
        hrv_today=500.0,
        rhr_today=-10.0,
        hrv_baseline=50.0,
        rhr_baseline=50.0,
    )

    assert good_score > poor_score
    assert 0.0 <= poor_score <= 100.0
    assert 0.0 <= good_score <= 100.0
    assert 0.0 <= extreme_score <= 100.0
    assert poor_explanation["recovery_score_simple"] == poor_score
    assert good_explanation["recovery_score_simple"] == good_score


def test_poor_sleep_reduces_recovery_for_same_hrv_and_resting_hr():
    # Sleep is a first-class recovery input, so the score should move even if
    # cardiovascular signals stay fixed.
    short_sleep_score, _ = health_recovery_daily._compute_recovery_score_with_baseline(
        sleep_minutes=300.0,
        hrv_today=55.0,
        rhr_today=50.0,
        hrv_baseline=55.0,
        rhr_baseline=50.0,
    )
    full_sleep_score, _ = health_recovery_daily._compute_recovery_score_with_baseline(
        sleep_minutes=480.0,
        hrv_today=55.0,
        rhr_today=50.0,
        hrv_baseline=55.0,
        rhr_baseline=50.0,
    )

    assert short_sleep_score < full_sleep_score


def test_recovery_score_is_deterministic_for_same_inputs():
    first = health_recovery_daily._compute_recovery_score_with_baseline(
        sleep_minutes=455.0,
        hrv_today=56.0,
        rhr_today=49.0,
        hrv_baseline=52.0,
        rhr_baseline=50.0,
    )
    second = health_recovery_daily._compute_recovery_score_with_baseline(
        sleep_minutes=455.0,
        hrv_today=56.0,
        rhr_today=49.0,
        hrv_baseline=52.0,
        rhr_baseline=50.0,
    )

    assert second == first


def test_recovery_daily_handles_missing_hrv_without_nan_or_crash(monkeypatch):
    # The recovery pipeline must degrade gracefully because HRV can be absent
    # on real days while other health signals are still usable.
    result, explanation_json, fake_conn = _run_recovery_daily(
        monkeypatch,
        sleep_row=(430.0, 40.0, 90.0, 70.0),
        resting_hr_row=(52.0,),
        hrv_row=(None,),
        weight_row=(72.3,),
        hrv_baseline_row=(54.0,),
        rhr_baseline_row=(50.0,),
    )

    assert result["recovery_score_simple"] is not None
    assert math.isnan(result["recovery_score_simple"]) is False
    assert result["hrv_daily_median_ms"] is None
    assert explanation_json["hrv_today"] is None
    assert explanation_json["hrv_score"] == 50.0
    assert explanation_json["recovery_score_simple"] == result["recovery_score_simple"]
    assert fake_conn.committed is True


def test_readiness_outputs_do_not_produce_nan_when_inputs_are_partial(monkeypatch):
    # Partial days are normal in a longitudinal pipeline. The fallback output
    # still needs to stay numerically valid for downstream consumers.
    result, explanation_json = _build_readiness_result(
        monkeypatch,
        load_row=None,
        recovery_row=(63.4, {"sleep_minutes": 455.0, "hrv_today": None, "rhr_today": 51.0}),
    )

    assert result["fallback_mode"] == "recovery_only"
    assert math.isnan(result["readiness_score"]) is False
    assert math.isnan(result["good_day_probability"]) is False
    assert explanation_json["recovery_score_simple"] == 63.4


def test_readiness_fallback_modes_are_deterministic(monkeypatch):
    # Fallback paths are part of the production contract, not error cases.
    # They must stay reproducible because upstream data completeness varies.
    full_first, _ = _build_readiness_result(
        monkeypatch,
        load_row=(4.0,),
        recovery_row=(66.0, {"sleep_minutes": 450.0, "hrv_today": 56.0, "rhr_today": 49.0}),
    )
    full_second, _ = _build_readiness_result(
        monkeypatch,
        load_row=(4.0,),
        recovery_row=(66.0, {"sleep_minutes": 450.0, "hrv_today": 56.0, "rhr_today": 49.0}),
    )
    load_only_first, _ = _build_readiness_result(
        monkeypatch,
        load_row=(4.0,),
        recovery_row=None,
    )
    load_only_second, _ = _build_readiness_result(
        monkeypatch,
        load_row=(4.0,),
        recovery_row=None,
    )
    recovery_only_first, _ = _build_readiness_result(
        monkeypatch,
        load_row=None,
        recovery_row=(66.0, {"sleep_minutes": 450.0, "hrv_today": 56.0, "rhr_today": 49.0}),
    )
    recovery_only_second, _ = _build_readiness_result(
        monkeypatch,
        load_row=None,
        recovery_row=(66.0, {"sleep_minutes": 450.0, "hrv_today": 56.0, "rhr_today": 49.0}),
    )

    assert full_second["readiness_score"] == full_first["readiness_score"]
    assert load_only_second["readiness_score"] == load_only_first["readiness_score"]
    assert recovery_only_second["readiness_score"] == recovery_only_first["readiness_score"]


def test_data_quality_marks_missing_recovery_inputs_for_load_only_readiness():
    data_quality = readiness_query._derive_data_quality(
        {
            "fallback_mode": "load_only",
            "freshness_norm": 62.0,
            "recovery_score_simple": None,
            "recovery_explanation": None,
        }
    )

    assert data_quality == {
        "sleep": "missing",
        "hrv": "missing",
        "resting_hr": "missing",
        "training": "ok",
    }
