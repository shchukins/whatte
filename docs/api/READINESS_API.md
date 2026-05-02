# Readiness API

## 1. Purpose

Этот документ описывает текущие readiness endpoints в Human Engine.

Оба endpoint работают только с уже сохраненным state layer.

---

## 2. Daily readiness

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

## 3. History

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
        "fallback_mode": null
      }
    }
  ]
}
```

### Notes

- `days` валидируется как целое число в допустимом диапазоне
- endpoint предназначен для history/trend UI
- источник истины для history — `readiness_daily`
