# Notifications

## 1. Purpose

Этот документ описывает текущие product-facing уведомления в Human Engine.

На текущем этапе основной реализованный notification flow:

- Daily Readiness Notification
- Activity Processed Notification
- Post-ride Telegram RPE request

---

## 2. Daily Readiness Notification

Daily Telegram notification строится на базе текущей Model V2 readiness architecture.

Источник данных:

- `readiness_daily`
- `readiness_daily.explanation_json`

Важно:

- notification layer не пересчитывает readiness
- notification layer использует уже materialized readiness state
- основное сообщение строится от score-level данных, а не от raw health samples

---

## 3. Message structure

```text
Human Engine · Today

Готовность: X
Статус: ...
Вероятность хорошего дня: X%

Свежесть: X
Восстановление: X

Восстановление:
• Сон: X
• HRV: X
• Пульс покоя: X

Комментарий:
...
```

Сообщение включает:

- readiness score
- status text
- good day probability
- freshness
- recovery score
- recovery breakdown
- короткий комментарий

---

## 4. Data source

Основной источник:

- `readiness_daily.readiness_score`
- `readiness_daily.good_day_probability`
- `readiness_daily.status_text`
- `readiness_daily.explanation_json`

Из `explanation_json` используются:

- `freshness`
- `recovery_score_simple`
- `recovery_explanation.sleep_score`
- `recovery_explanation.hrv_score`
- `recovery_explanation.rhr_score`

---

## 5. Comment style

Комментарий в текущем backend:

- короткий
- rule-based
- explainable
- не использует LLM или скрытую логику

Типовые случаи:

- если breakdown недоступен, комментарий остается нейтральным
- если самый слабый компонент recovery — сон, акцент делается на сне
- если самый слабый компонент — HRV, акцент делается на incomplete recovery
- если самый слабый компонент — resting HR, акцент делается на elevated resting HR
- если freshness сильно отрицательный, отдельно отмечается накопленная усталость
- если freshness и recovery оба хорошие, отдельно отмечается хороший день по состоянию

---

## 6. Principles

Notification message должен быть:

- коротким
- объяснимым
- без перегрузки
- ориентированным на пользователя

Нельзя:

- превращать сообщение в dump внутренних формул
- показывать raw health data как основной текст, если уже есть score-level summary
- подменять readiness text генеративным слоем

---

## 7. Fallback

Если `readiness_daily` недоступен:

- backend может использовать более старый fallback summary
- это fallback path, а не основной source of truth

Основной path:

- `readiness_daily` -> `explanation_json` -> Telegram message

---

## 3. Activity Processed Notification

После успешной ingestion обработки Strava activity backend отправляет:

1. обычное сообщение об обработанной тренировке
2. отдельное Telegram message с inline RPE buttons

Callback payload:

- `rpe:{activity_id}:{score}`

Пример:

- `rpe:18403528422:4`

Принципы:

- one-tap
- asynchronous
- idempotent
- linked to `strava_activity_id`

---

## 4. Post-ride feedback persistence

После callback backend:

- валидирует activity
- upsert-ит row в `activity_subjective_feedback`
- сохраняет `source = telegram`
- сохраняет historical readiness snapshot в `context_json`
- редактирует Telegram message в краткое подтверждение

Важно:

- repeated button presses обновляют existing row
- duplicate callbacks не создают дубликаты
- feedback collection не меняет readiness calculation logic
