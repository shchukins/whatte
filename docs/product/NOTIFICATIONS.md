# Notifications

## 1. Purpose

Этот документ описывает текущую notification architecture в Whatte.

Цель notification layer:

- доставить уже рассчитанное состояние пользователю
- собрать low-friction subjective feedback
- не вмешиваться в deterministic core calculations

Текущие notification flows:

- Daily Readiness Notification
- Activity Processed Notification
- Post-ride RPE prompt
- Next-day recovery prompt

---

## 2. Architectural role

Notification layer находится после deterministic state layers.

Он:

- читает уже materialized readiness state
- отправляет user-facing сообщения
- собирает subjective feedback через Telegram callbacks

Он не:

- пересчитывает readiness
- меняет recommendation logic
- использует LLM для core messaging decisions

High-level flow:

```text
raw inputs -> derived state -> readiness -> recommendation -> notification / feedback collection
```

---

## 3. Daily readiness notification

Daily Telegram notification строится на базе текущей readiness architecture.

Source of truth:

- `readiness_daily.readiness_score`
- `readiness_daily.good_day_probability`
- `readiness_daily.status_text`
- `readiness_daily.explanation_json`
- deterministic recommendation / briefing output

Важно:

- notification layer не пересчитывает readiness
- notification layer использует уже materialized readiness state
- основное сообщение строится от score-level данных, а не от raw health samples

---

## 4. Daily readiness message style

Текущее daily message должно быть:

- коротким
- explainable
- rule-based
- без перегрузки

Сообщение обычно включает:

- readiness score
- status text
- good day probability
- freshness
- recovery score
- recovery breakdown
- короткий deterministic комментарий

Нельзя:

- превращать сообщение в dump внутренних формул
- показывать raw health data как основной текст
- подменять readiness text генеративным слоем

---

## 5. Subjective feedback collection philosophy

Telegram feedback prompts нужны для longitudinal subjective feedback collection.

Принципы UX:

- feedback optional
- low-friction
- asynchronous
- one message per prompt
- one-tap answer в текущем MVP
- максимум три taps как потолок для будущих flows

Почему это важно:

- calibration требует много repeated observations
- repeated observations требуют минимального friction
- более короткий flow обычно ценнее, чем более богатая анкета

Best-effort behavior:

- feedback persistence приоритетнее Telegram UX confirmation
- callback acknowledgement best-effort
- message edit best-effort
- Telegram error после DB write не должен ломать feedback persistence

---

## 6. Post-ride RPE prompt

После успешной обработки Strava activity backend отправляет:

1. activity processed message
2. отдельный Telegram prompt с inline RPE buttons

Callback format:

- `rpe:{activity_id}:{score}`

Example:

- `rpe:18403528422:4`

Semantics:

- feedback type: `post_ride_rpe`
- activity-level feedback
- natural key: `strava_activity_id + feedback_type`

После callback backend:

- валидирует activity и score
- upsert-ит row в `activity_subjective_feedback`
- сохраняет normalized fields
- сохраняет `feedback_schema_version = v1_extensible`
- сохраняет optional `feedback_payload`
- сохраняет historical context snapshot в `context_json`
- best-effort подтверждает callback
- best-effort редактирует message в краткое подтверждение

Важно:

- repeated taps обновляют canonical row
- duplicate callbacks не создают дубликаты
- feedback collection не меняет readiness logic

---

## 7. Next-day recovery prompt

Next-day recovery prompt собирает delayed outcome после предыдущего training day.

Почему этот signal важен:

- immediate RPE описывает восприятие самой сессии
- next-day recovery лучше отражает накопленный recovery effect
- для readiness validation delayed recovery often provides stronger calibration signal

Current MVP behavior:

- prompt отправляется отдельно от post-ride RPE
- worker scheduler запускает batch orchestration утром по UTC часу `NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC`
- repeated worker loops безопасны, потому что duplicate prevention хранится в БД
- prompt можно отправить через backend service / debug endpoint
- batch scheduling можно проверить через debug endpoint

Prompt usefulness conditions:

- предыдущий день имеет `daily_training_load.tss > 0`
- или предыдущий день имеет `daily_training_load.activities_count > 0`
- или есть activities в `strava_activity_raw` за предыдущую дату

Callback format:

- `recovery:{user_id}:{target_date}:{score}`

Semantics:

- feedback type: `next_day_recovery`
- date-level feedback
- natural key: `user_id + activity_date + feedback_type` when `strava_activity_id is null`

После callback backend:

- валидирует `target_date` и score
- upsert-ит row в `activity_subjective_feedback`
- пишет `activity_date = target_date`
- сохраняет previous-day linkage в `feedback_payload`
- сохраняет historical readiness / recommendation snapshot в `context_json`, если доступно
- best-effort подтверждает callback
- best-effort редактирует message в `Recovery feedback recorded ✓`

---

## 8. Data rationale inside feedback flows

Feedback rows intentionally separate three layers of information:

Normalized fields:

- `feedback_type`
- `feedback_value`
- `feedback_score`
- `source`

These support filtering, analytics, and stable queries.

Extensible payload:

- feedback-family-specific details
- previous-day linkage
- future optional dimensions

Historical context snapshot:

- readiness at feedback time
- recommendation at feedback time
- recovery breakdown at feedback time when available

Почему snapshot важен:

- later model changes should not rewrite past observations
- calibration compares what the system predicted then versus what the athlete reported then
- recommendation evaluation requires historical recommendation context, not current recomputed state

---

## 9. Manual testing / debug path

Для ручной проверки recovery prompt используется:

- `POST /debug/feedback/recovery-prompt/{user_id}/{target_date}`

Expected response includes:

- `ok`
- `skipped`
- `reason`
- `user_id`
- `target_date`
- `previous_date`
- `activities_count`
- `previous_training_load`
- `linked_activity_ids`

---

## 10. Future notification roadmap

Возможные дальнейшие шаги:

- morning recovery scheduler
- sport-specific second-tap feedback
- iOS-native subjective feedback collection
- richer reminder policies
- recommendation calibration loops based on accumulated feedback

Это roadmap, а не текущая backend behavior.


## 11. Scheduled recovery prompt orchestration

Delivery state now persists in `subjective_feedback_prompt_log`.

Why this is separate from `activity_subjective_feedback`:

- prompt delivery happens before user feedback exists
- duplicate prevention belongs to orchestration, not to outcome rows
- delivery failures and retries need their own lifecycle

Current idempotency guarantees:

- at most one prompt-log row per `(user_id, prompt_type, target_date)`
- repeated scheduler runs do not create duplicate sends after a `sent` row exists
- existing `next_day_recovery` feedback suppresses prompt delivery entirely
- repeated callbacks still upsert into the same date-level feedback row

Current operational limitation:

- prompt scheduling is UTC-based rather than user-timezone-based
- Telegram delivery still uses the current backend-wide chat configuration, which matches the existing notification architecture
