# Readiness API

## 1. Purpose

Этот документ описывает текущие readiness endpoints в Human Engine.

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
- `explanation_json`

### Notes

- используется текущая Model V2 baseline
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
  "readiness_score": 55.7,
  "good_day_probability": 0.557,
  "status_text": "Нормальная готовность",
  "explanation": {
    "fallback_mode": null,
    "freshness": 4.0,
    "freshness_norm": 54.0,
    "recovery_score_simple": 58.2,
    "weights": {
      "freshness_norm": 0.6,
      "recovery_score_simple": 0.4
    },
    "formula": "0.6 * freshness_norm + 0.4 * recovery_score_simple",
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

### Main fields

- `readiness_score`
- `good_day_probability`
- `status_text`
- `explanation`
- `recommendation`
- `reason`
- `briefing`
- `briefing_text`

### Notes

- source of truth is `readiness_daily`
- `recommendation`, `reason` and `briefing` are derived by deterministic decision logic
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
- фильтрует по `user_id` и `version = 'v2'`
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
  "explanation": {
    "fallback_mode": null,
    "freshness": 4.0,
    "freshness_norm": 54.0,
    "recovery_score_simple": 58.2,
    "weights": {
      "freshness_norm": 0.6,
      "recovery_score_simple": 0.4
    },
    "formula": "0.6 * freshness_norm + 0.4 * recovery_score_simple",
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
- если rows отсутствуют, возвращается `404`
- рекомендован для iOS Today screen вместо optimistic request на local today

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
