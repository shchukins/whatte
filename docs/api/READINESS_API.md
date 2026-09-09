# Readiness API

## 1. Purpose

Этот документ описывает текущие readiness endpoints в Whatte.

GET endpoints работают только с уже сохраненным state layer.

---

## 2. Recompute daily readiness

### Endpoint

```text
POST /api/v1/model/readiness-daily/{user_id}/{date}
```

### Purpose

- пересчитать readiness для одной даты
- сохранить результат в `readiness_daily`

### Main fields

- `readiness_score`
- `good_day_probability`
- `status_text`
- `fallback_mode`
- `model_version`
- `signal_families`
- `reason_codes`
- `explanation_json`

### Notes

- используется текущая версия `v2_signal_composition_response_v1`
- readiness сохраняется в `readiness_daily`
- fallback mode отражает, какой контур был доступен при расчете

---

## 3. Get daily readiness

### Endpoint

```text
GET /api/v1/model/readiness-daily/{user_id}/{date}
```

### Purpose

- прочитать readiness за конкретную дату
- добавить decision layer output поверх сохраненного `readiness_daily`
- не делать recomputation

### Response shape

```json
{
  "ok": true,
  "user_id": "sergey",
  "date": "2026-04-26",
  "readiness_score": 53.0,
  "good_day_probability": 0.53,
  "status_text": "Нормальная готовность",
  "freshness_state": "fresh",
  "freshness_reason_codes": [],
  "readiness_computed_at": "2026-04-26T05:00:00+00:00",
  "recovery_source_at": "2026-04-26",
  "training_source_at": "2026-04-26",
  "data_quality": {
    "sleep": "ok",
    "hrv": "ok",
    "resting_hr": "ok",
    "training": "ok"
  },
  "model": {
    "name": "readiness_signal_composition",
    "version": "v2_signal_composition_response_v1",
    "formula_version": "signal_weighted_response_v1"
  },
  "reason_codes": [],
  "signal_families": {
    "freshness": {
      "availability": "available",
      "used": true,
      "score": 54.0,
      "configured_weight": 0.6,
      "effective_weight": 0.6,
      "contribution": 32.4,
      "reason_codes": []
    },
    "response": {
      "availability": "available",
      "used": true,
      "score": 45.0,
      "configured_weight": 0.2,
      "effective_weight": 0.2,
      "contribution": 9.0,
      "reason_codes": [],
      "data": {
        "activity_id": 123,
        "version": "v1",
        "scoring": {
          "age_days": 1,
          "recency": 1.0,
          "channels": {
            "objective": 50.0,
            "subjective": 40.0
          },
          "selected_subjective_metric": "session_rpe_load_per_tss"
        }
      }
    },
    "physiology": {
      "availability": "available",
      "used": true,
      "score": 58.2,
      "configured_weight": 0.2,
      "effective_weight": 0.2,
      "contribution": 11.64,
      "reason_codes": []
    }
  },
  "explanation": {
    "fallback_mode": null,
    "freshness": 4.0,
    "freshness_norm": 54.0,
    "recovery_score_simple": 58.2,
    "feeling_score": null,
    "formula": "signal_weighted_response_v1",
    "recovery_explanation": {
      "sleep_score": 82.8,
      "hrv_score": 42.1,
      "rhr_score": 49.5
    }
  },
  "recommendation": "endurance",
  "reason": "Readiness score is 53/100. Freshness is available at 54/100. Recovery is available at 58.2/100. Recommendation is endurance.",
  "briefing": "Сегодня нормальная готовность. Рекомендуется спокойная аэробная тренировка.",
  "briefing_text": "Сегодня нормальная готовность. Рекомендуется спокойная аэробная тренировка."
}
```

### Main fields

- `readiness_score`
- `good_day_probability`
- `status_text`
- `data_quality`
- `model`
- `signal_families`
- `reason_codes`
- `explanation`
- `recommendation`
- `reason`
- `briefing`
- `briefing_text`

### Notes

- source of truth is `readiness_daily`
- GET endpoints select `version = v2_signal_composition_response_v1`; legacy
  `v2` and `v2_signal_composition` rows remain stored but are not silently
  substituted
- `recommendation`, `reason` and `briefing` are derived by deterministic decision logic
- `data_quality` shows which input families were actually available; it is not a confidence score
- current MVP returns `training = ok|missing`; `partial` is reserved for future unsupported/continuity-only load detection
- `briefing_text` is kept for client compatibility
- missing row returns `404`

---

## 4. Get latest readiness

### Endpoint

```text
GET /api/v1/model/readiness-daily/{user_id}/latest
```

### Purpose

- прочитать последний доступный readiness для пользователя
- вернуть уже сохраненный row из `readiness_daily`
- не делать recomputation
- использоваться клиентами как стабильный endpoint около границы суток

### Behavior

- читает `readiness_daily`
- фильтрует по `user_id` и
  `version = 'v2_signal_composition_response_v1'`
- выбирает `order by date desc limit 1`
- возвращает тот же response shape, что и date-specific GET endpoint

### Response shape

```json
{
  "ok": true,
  "user_id": "sergey",
  "date": "2026-05-02",
  "readiness_score": 55.7,
  "good_day_probability": 0.557,
  "status_text": "Нормальная готовность",
  "data_quality": {
    "sleep": "ok",
    "hrv": "ok",
    "resting_hr": "ok",
    "training": "ok"
  },
  "explanation": {
    "fallback_mode": null,
    "freshness": 4.0,
    "freshness_norm": 54.0,
    "recovery_score_simple": 58.2,
    "formula": "signal_weighted_response_v1",
    "recovery_explanation": {
      "sleep_score": 82.8,
      "hrv_score": 42.1,
      "rhr_score": 49.5
    }
  },
  "recommendation": "endurance",
  "reason": "Readiness score is 55.7/100. Freshness is available at 54/100. Recovery is available at 58.2/100. Recommendation is endurance.",
  "briefing": "Сегодня нормальная готовность. Рекомендуется спокойная аэробная тренировка.",
  "briefing_text": "Сегодня нормальная готовность. Рекомендуется спокойная аэробная тренировка."
}
```

### Notes

- source of truth is `readiness_daily`
- endpoint read-only и не создает новые rows
- response includes `data_quality` derived from stored explanation payloads
- response includes the backend-owned readiness source-data freshness contract
- если rows отсутствуют, возвращается `404`
- используется Web Today и другими read-only surfaces

### Readiness source-data freshness contract

The API fields `freshness_state` and `freshness_reason_codes` describe the
currency of the source rows used to compute readiness. They do **not** describe
the physiological load metric named `freshness`, which remains stored inside
the model explanation and `load_state_daily_v2`.

The source-data threshold is an exact user-day boundary:

- a recovery or training/load source is current when its snapshotted source
  date equals the readiness target `date`;
- a source date before the target date is stale;
- a missing or unusable source date is missing evidence;
- `readiness_computed_at` must exist and must not precede the target user-day.

The timezone is snapshotted from the explicit `WHATTE_TIMEZONE` configuration
when readiness is recomputed. The default is `Europe/Moscow`; the server's
implicit local timezone and historical HealthKit payloads are not used.

States:

- `fresh`: readiness is for the current local evaluation date and both source
  families are current;
- `partial`: exactly one source family is absent under the existing
  `recovery_only` or `load_only` fallback, and the available family is current;
- `stale`: the latest readiness date or at least one available source/computation
  date is older than its required day boundary;
- `missing`: required evidence is absent or unusable. Legacy rows without
  `explanation.source_timestamps` are always `missing`.

Stable reason codes currently emitted:

- `readiness_date_before_local_today`
- `readiness_date_after_local_today`
- `readiness_computed_at_missing`
- `readiness_computed_at_before_readiness_date`
- `recovery_source_missing`
- `recovery_source_stale`
- `recovery_source_after_readiness_date`
- `training_source_missing`
- `training_source_stale`
- `training_source_after_readiness_date`
- `legacy_timestamp_snapshot_missing`
- `fallback_recovery_only`
- `fallback_load_only`
- `readiness_freshness_context_invalid`

`readiness_computed_at` is sourced from `readiness_daily.updated_at`.
`recovery_source_at` and `training_source_at` expose the stored source-row dates
used by that computation. Date precision is intentional; the current derived
source tables do not provide a more meaningful source event timestamp.

For `latest`, the readiness date is compared with the current date in the
snapshotted timezone. For the date-specific endpoint, freshness is evaluated
relative to the requested readiness target date. Consequently, a correct
historical snapshot does not become stale merely because it is viewed later.

The history endpoint is unchanged and does not add freshness metadata to every
point. This preserves its compact, backward-compatible trend contract.

This contract is separate from:

- model/load `freshness`: the physiological `fitness - fatigue_total` metric;
- `data_quality`: completeness of individual recovery/training inputs;
- model confidence: not represented by this freshness state.

---

## 5. History

### Endpoint

```text
GET /api/v1/model/readiness-daily/{user_id}/history?days=7
```

### Purpose

- вернуть последние `N` readiness points для пользователя
- отдать их в порядке возрастания даты для UI trend

### Behavior

- читает `readiness_daily`
- не делает recomputation
- выбирает последние rows через `order by date desc limit N`
- затем разворачивает результат в Python в ascending order

### Response shape

```json
{
  "ok": true,
  "user_id": "sergey",
  "days": 7,
  "points": [
    {
      "date": "2026-04-26",
      "readiness_score": 59.8,
      "good_day_probability": 0.598,
      "status_text": "Нормальная готовность",
      "explanation": {
        "fallback_mode": null,
        "freshness_norm": 55.0,
        "recovery_score_simple": 67.0
      }
    }
  ]
}
```

### Notes

- `days` валидируется как целое число в допустимом диапазоне
- endpoint предназначен для history/trend UI
- источник истины для history — `readiness_daily`
- current history points do not include `recommendation`, `reason` or `briefing`
