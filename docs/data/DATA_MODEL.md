# Data Model

## 1. Purpose

Этот документ описывает текущую модель данных Whatte.

Цель:

- зафиксировать структуру хранения
- обеспечить воспроизводимость расчетов
- разделить raw, normalized и derived данные

---

## 2. Principles

Модель данных должна:

- сохранять raw payloads без изменения
- позволять повторный расчет derived state
- быть прозрачной
- явно отделять implemented и planned layers

---

## 3. Data layers

### 3.1 Raw data

Необработанные данные из внешних источников.

Примеры:

- `strava_activity_raw`
- `healthkit_ingest_raw`

Свойства:

- не изменяются
- сохраняются полностью
- являются источником воспроизводимости

---

### 3.2 Ingestion data

Данные, связанные с процессом загрузки.

Содержат:

- webhook события
- jobs
- статусы обработки

---

### 3.3 Normalized data

Нормализованные таблицы, полученные из raw payloads.

Примеры:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

---

### 3.4 Derived daily state

Производные таблицы, которые могут пересчитываться.

Примеры:

- `daily_training_load`
- `health_recovery_daily`
- `load_state_daily_v2`
- `readiness_daily`

---

## 4. Core ingestion entities

### 4.1 `strava_webhook_event`

События от Strava.

Назначение:

- триггер ingestion

---

### 4.2 `strava_activity_ingest_job`

Задача на загрузку активности.

Назначение:

- управление асинхронной загрузкой

---

### 4.3 `strava_activity_raw`

Сырые данные активности из Strava API.

Назначение:

- источник для downstream расчетов

Поля дедупликации (migration `007`):

- `duplicate_of_activity_id` связывает исключённую запись с canonical Strava
  activity; для автоматической MyWhoosh/Garmin пары canonical всегда MyWhoosh
- `is_excluded` и `exclusion_reason` управляют включением в агрегаты
- confidence, reason, detection timestamp/version сохраняют audit trail
- manual override и candidate id сохраняют ручное exclude/separate решение

`activity_metrics` дубля физически сохраняются. Запрос
`daily_training_load` фильтрует `is_excluded = false`, поэтому fitness,
load-state, freshness и readiness получают одну физическую тренировку.

---

### 4.4 `activity_delivery_log`

Per-activity ledger для идемпотентной доставки `training_processed` и
`post_ride_rpe`. Unique key: `(activity_id, delivery_type)`, где activity id
разрешён до canonical.

---

### 4.5 `healthkit_ingest_raw`

Сохранённый сырой payload retired HealthKit sync path.

Назначение:

- воспроизводимость исторического HealthKit ingest
- исходный источник для нормализации health data

---

## 5. Current normalized and derived entities

### 5.1 `daily_training_load`

Дневная агрегированная нагрузка из тренировок.

Назначение:

- вход для `load_state_daily_v2`

Ключевое поле:

- `tss`

---

### 5.2 `health_sleep_night`

Нормализованная запись о сне.

Назначение:

- хранить sleep night по `wake_date`
- быть входом для recovery aggregation

Ключевые поля:

- `wake_date`
- `sleep_start_at`
- `sleep_end_at`
- `total_sleep_minutes`
- `awake_minutes`
- `core_minutes`
- `rem_minutes`
- `deep_minutes`
- `in_bed_minutes`

---

### 5.3 `health_resting_hr_daily`

Нормализованный resting HR по дате.

Ключевые поля:

- `date`
- `bpm`

---

### 5.4 `health_hrv_sample`

Нормализованные HRV samples.

Назначение:

- хранить sample-level HRV
- поддерживать day-level aggregation через median

Ключевые поля:

- `sample_start_at`
- `value_ms`

---

### 5.5 `health_weight_measurement`

Нормализованные измерения веса.

Ключевые поля:

- `measured_at`
- `kilograms`

---

### 5.6 `health_recovery_daily`

Дневная recovery-агрегация из health tables.

Источник:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

Ключевые поля:

- `sleep_minutes`
- `awake_minutes`
- `rem_minutes`
- `deep_minutes`
- `resting_hr_bpm`
- `hrv_daily_median_ms`
- `weight_kg`
- `recovery_score_simple`
- `recovery_explanation_json`

Комментарий:

- поле `recovery_score_simple` исторически сохраняет имя для совместимости
- текущий backend считает его через baseline-aware scoring layer
- breakdown и baseline-компоненты сохраняются в `recovery_explanation_json`

---

### 5.7 `load_state_daily_v2`

Load model v2.

Источник:

- `daily_training_load`
- календарный диапазон между training и recovery датами пользователя

Свойства расчета:

- рассчитывается по непрерывной календарной оси
- в дни без тренировок используется `tss = 0`
- текущий `load_input_nonlinear` фактически равен линейному input по TSS

Ключевые поля:

- `tss`
- `load_input_nonlinear`
- `fitness`
- `fatigue_fast`
- `fatigue_slow`
- `fatigue_total`
- `freshness`
- `version`

---

### 5.8 `readiness_daily`

Отдельный readiness layer.

Источник:

- `load_state_daily_v2`
- `health_recovery_daily`
- `activity_subjective_feedback` for optional date-level morning feeling

Ключевые поля:

- `freshness`
- `recovery_score_simple`
- `readiness_score_raw`
- `readiness_score`
- `good_day_probability`
- `status_text`
- `explanation_json`
- `version`

Current writes use `version = v2_signal_composition_response_v1`. The
`(user_id, date, version)` key preserves legacy `v2` and
`v2_signal_composition` rows instead of rewriting them. The
`explanation_json.signal_families` object stores availability, usage, score,
effective weight, contribution, reason codes, and family-specific data for
`load`, `freshness`, `response`, `feeling`, and `physiology`.

`updated_at` is the public `readiness_computed_at` evidence. No schema migration
is required for readiness source-data freshness. Each new computation stores an
immutable-for-that-computation snapshot inside `explanation_json`:

```json
{
  "source_timestamps": {
    "recovery_source_at": "2026-05-02",
    "training_source_at": "2026-05-02",
    "timezone": "Europe/Moscow"
  }
}
```

The `*_source_at` values currently have date precision because they identify
the exact daily derived rows consumed by readiness. They must not be interpreted
as fabricated event timestamps. A recomputation replaces the snapshot together
with the rest of `explanation_json`; historical API reads use the stored
snapshot and never join newly arrived live source rows. Legacy rows without the
section remain readable and are classified as `missing`.

---

### 5.9 `activity_response_metrics`

Versioned activity-level training-response layer.

Sources:

- canonical `strava_activity_raw`
- `activity_metrics` version `v1`
- raw power / HR / time streams
- optional effective 1-10 RPE from `activity_rpe_resolution`

Key fields:

- `version`
- `activity_type`, `activity_date`, `duration_s`
- `intensity_factor`, `intensity_band`
- `avg_power_w`, `normalized_power_w`, `avg_hr_bpm`
- `avg_power_to_hr`, `normalized_power_to_hr`
- `aerobic_decoupling_pct`
- `rpe_score`, `session_rpe_load`
- `rpe_per_intensity_factor`, `session_rpe_load_per_tss`
- `availability_json`, `baseline_json`, `explanation_json`

The natural key is `(strava_activity_id, version)`. Baselines use earlier
canonical activities of the same activity type and intensity band. Version 1
stores per-metric medians and deviations but no aggregate response score.
Historical `v1` uses the 1-5 scale; current `v2_rpe_1_10` uses only 1-10
observations and comparable rows of its own version.

### 5.9a Source RPE observations

`activity_rpe_observation` stores independent `telegram`, `web`, and
`strava` 1-10 scores for a canonical activity, with `scale_version`,
`observed_at`, `received_at`, and `source_payload`. Its key is
`(canonical_activity_id, source)`. `schema_version` identifies the
observation payload contract independently of `scale_version`.
`activity_rpe_resolution` persists one
effective score/source and the disagreement flag. Strava has precedence,
followed by Telegram and Web. The historical 1-5
`activity_subjective_feedback` rows are retained, not converted.

Read-only calibration records expose `workout_outcome_v1` as independent
activity and training-day targets. Its source, scale, missingness, and temporal
eligibility rules are documented in
[`CALIBRATION_RECORDS.md`](CALIBRATION_RECORDS.md). No outcome table or new
feedback write path is introduced by this contract.

Full formula and eligibility contract:
[`docs/models/TRAINING_RESPONSE.md`](../models/TRAINING_RESPONSE.md).

### 5.9b Manual physiology observations

`manual_physiology_observation` stores the current optional manual sleep, HRV,
and resting-HR values for one user/local date. The natural key is
`(user_id, local_date)`. Nullable values remain unavailable rather than being
filled with zero or a neutral score.

`manual_physiology_observation_revision` is the append-only audit history for
actual changes. It preserves a full observation snapshot, source, received
time, schema version, revision number, and the submitted fields that changed.
The persistence contract is documented in
[`MANUAL_PHYSIOLOGY.md`](MANUAL_PHYSIOLOGY.md). It does not calculate a
baseline, recovery score, or readiness value.

### 5.9c Personal physiology features

`personal_physiology_feature_daily` persists reproducible, versioned
personal-relative features from `manual_physiology_observation` only. It
stores per-signal baseline sample counts, maturity/availability, explicit
timestamp state, and formula configuration alongside HRV ratio/deviation,
resting-HR delta, and sleep deviation/debt. It is a research and feature-vector
input; it does not replace raw observations, use HealthKit, or alter readiness.

### 5.10 `research_experiment`

`research_experiment` is a research-only audit log for offline model
experiments. It stores identifiers and immutable metadata rather than raw
personal data: hypothesis, candidate model/configuration fingerprint, temporal
dataset version/hash/partition, frozen evaluator version/specification hash,
optional parent or baseline experiment references, and terminal metrics or
failure evidence.

Its lifecycle is intentionally narrow:

- a record is created as `running`;
- it may transition once to `candidate`, `rejected`, or `failed`;
- terminal records cannot be changed or deleted.

`promoted` is reserved in the persisted status vocabulary for the later
manual-promotion contract. This schema and its service cannot transition an
experiment to that state. The record does not execute a candidate, expose an
API, schedule research, or write production readiness, feedback, activity, or
user-state tables.

### 5.11 `activity_subjective_feedback`

Слой user-reported subjective feedback.

Назначение:

- сохранить ground truth о том, как ощущалась тренировка
- сохранить ground truth о том, как ощущалось восстановление на следующий день
- отделить evaluation / calibration dataset от deterministic core calculations

Источники:

- Telegram callback после activity notification
- Telegram callback после next-day recovery prompt
- Web Today one-tap recovery and RPE forms

Ключевые поля:

- `user_id`
- `strava_activity_id` nullable для date-level feedback
- `canonical_activity_id` для аналитической связи с canonical workout при
  сохранении исходного callback target
- `activity_date`
- `feedback_type`
- `feedback_value`
- `feedback_score`
- `source`
- `feedback_schema_version`
- `feedback_payload`
- `context_json`

Feedback types:

- `post_ride_rpe`
- `next_day_recovery`

Active sources:

- `telegram`
- `web`

Архитектурные слои внутри row:

- normalized queryable fields:
  - `feedback_type`
  - `feedback_value`
  - `feedback_score`
  - `source`
- extensible payload:
  - `feedback_payload`
- historical derived-state snapshot:
  - `context_json`

Семантика linkage:

- activity-level feedback использует `strava_activity_id`
- date-level feedback использует `activity_date` как canonical target
- `strava_activity_id = null` для recovery feedback является intentional, а не missing reference

Особенности:

- normalized fields остаются основным query surface
- `feedback_payload` добавляет extensible JSON-слой и не заменяет нормализованную модель
- historical 1-5 RPE and current next-day recovery rows use
  `feedback_schema_version = v1_extensible`; current RPE uses the separate
  source-observation table
- `feedback_schema_version` version-ит payload semantics, а не базовые normalized поля
- `context_json` хранит historical readiness / recommendation snapshot на момент feedback
- snapshot хранится исторически, чтобы будущие model changes не переписывали observed past state

Идемпотентность и уникальность:

- activity-level уникальность обеспечивается partial unique index по `(strava_activity_id, feedback_type)` при `strava_activity_id is not null`
- date-level уникальность обеспечивается partial unique index по `(user_id, activity_date, feedback_type)` при `strava_activity_id is null`

Почему partial indexes:

- activity-level и date-level feedback имеют разные natural keys
- одна общая уникальность не покрывает обе модели безопасно
- repeated Telegram taps должны обновлять canonical row, а не создавать дубликаты

Пример activity-level row:

```json
{
  "strava_activity_id": 17855535922,
  "activity_date": "2026-05-14",
  "feedback_type": "post_ride_rpe",
  "feedback_value": "hard",
  "feedback_score": 4,
  "source": "telegram",
  "feedback_schema_version": "v1_extensible",
  "feedback_payload": {},
  "context_json": {
    "readiness_score": 63.5,
    "recommendation": "moderate"
  }
}
```

Пример date-level row:

```json
{
  "strava_activity_id": null,
  "activity_date": "2026-05-15",
  "feedback_type": "next_day_recovery",
  "feedback_value": "fresh",
  "feedback_score": 4,
  "source": "telegram",
  "feedback_schema_version": "v1_extensible",
  "feedback_payload": {
    "target_date": "2026-05-15",
    "previous_date": "2026-05-14",
    "previous_training_load": 85.0,
    "previous_activities_count": 2,
    "linked_activity_ids": [17855535922, 17855535923]
  },
  "context_json": {
    "snapshot_date": "2026-05-15",
    "readiness_score": 58.0,
    "recommendation": "endurance"
  }
}
```

### 5.11 `notification_log`

Delivery-state журнал для at-most-once уведомлений.

Ключевые поля:

- `user_id`
- `notification_type`
- `notification_date`
- `recovery_date`
- `freshness_status`
- `delivery_status`
- `telegram_chat_id`
- `telegram_message_id`
- `sent_at`
- `updated_at`
- `content_fingerprint`
- `payload_json`
- `created_at`

Для `daily_readiness` уникальность
`(user_id, notification_type, notification_date)` остается дневным atomic claim
между повторными worker attempts, но больше не означает, что row навсегда
блокирует обновления. Под `select ... for update` delivery layer
сравнивает `recovery_date`, `freshness_status` и SHA-256
`content_fingerprint`. Полный внешний send/edit lifecycle дополнительно
сериализуется PostgreSQL advisory lock по пользователю и дате briefing.

Состояния доставки:

- `claimed` — первичная отправка занята одним процессом;
- `sent` — создано обычное Telegram-сообщение;
- `updating` — процесс занял обновление существующего сообщения;
- `updated` — существующее сообщение успешно изменено через `editMessageText`;
- `superseded` — edit был невозможен и создано одно отдельное update-сообщение;
- `failed` — первичная доставка не состоялась и может быть безопасно повторена.

Старые rows не удаляются. При успешной отправке сохраняются Telegram
`chat_id/message_id`, чтобы изменившийся briefing можно было обновить.
`payload_json` остается диагностическим снимком текста и
freshness metadata.

Этот журнал относится к delivery layer и не влияет на recovery, readiness или
recommendation.

---

## 6. Relationships

Текущие связи:

- `strava_webhook_event -> strava_activity_ingest_job` (1:N)
- `strava_activity_ingest_job -> strava_activity_raw` (1:1 / 1:N depending on retries)
- `strava_activity_raw -> daily_training_load` (N:1 through processing layer)
- `healthkit_ingest_raw -> health_sleep_night` (1:N)
- `healthkit_ingest_raw -> health_resting_hr_daily` (1:N)
- `healthkit_ingest_raw -> health_hrv_sample` (1:N)
- `healthkit_ingest_raw -> health_weight_measurement` (1:N)
- `daily_training_load -> load_state_daily_v2` (N:1)
- `health_sleep_night -> health_recovery_daily` (N:1)
- `health_resting_hr_daily -> health_recovery_daily` (N:1)
- `health_hrv_sample -> health_recovery_daily` (N:1)
- `health_weight_measurement -> health_recovery_daily` (N:1)
- `health_recovery_daily -> readiness_daily` (N:1)
- `load_state_daily_v2 -> readiness_daily` (N:1)
- `strava_activity_raw -> activity_subjective_feedback` (1:N by feedback type)

---

## 7. Current data flow

### 7.1 Health contour

```text
HealthKit
↓
healthkit_ingest_raw
↓
health_sleep_night / health_resting_hr_daily / health_hrv_sample / health_weight_measurement
↓
health_recovery_daily
```

Комментарий:

- `health_recovery_daily` materializes day-level recovery state
- `recovery_explanation_json` хранит breakdown текущего baseline scoring

### 7.2 Load contour

```text
Strava
↓
strava raw / processing
↓
daily_training_load
↓
load_state_daily_v2
```

Комментарий:

- `load_state_daily_v2` materializes calendar-continuous load state
- для дней без тренировки используется `tss = 0`

### 7.3 Readiness contour

```text
load_state_daily_v2 + health_recovery_daily
↓
readiness_daily
```

Комментарий:

- readiness хранится отдельно от load layer
- `good_day_probability` является отдельным output внутри `readiness_daily`

### 7.4 Subjective feedback contour

```text
Strava activity notification
↓
Telegram inline callback
↓
activity_rpe_observation (1-10) + historical activity_subjective_feedback (1-5)
```

Комментарий:

- субъективный feedback хранится отдельно от deterministic model state
- snapshot в `context_json` фиксирует состояние модели на момент ответа
- изменение effective 1-10 RPE запускает versioned response/readiness recompute после commit
- date-level `next_day_recovery` читается новой readiness composition как
  explicit `feeling` signal; upsert запускает deterministic recompute, но не
  переписывает feedback snapshot или legacy readiness version
- `decision_context_snapshot` append-only фиксирует решение в точках доставки,
  до recovery check-in и после его deterministic recompute; таблица не является
  входом readiness или recommendation

---

## 8. Reproducibility

Для обеспечения воспроизводимости:

- raw данные не изменяются
- normalized и derived таблицы можно пересчитать
- readiness считается из сохраненных load, feeling и optional physiology layers

---

## 9. Storage strategy

### Raw data

- хранить всегда
- не удалять без отдельного решения

### Normalized and derived data

- хранить как materialized daily state
- поддерживать пересчет из upstream layers

Общая стратегия versioning и retention еще остается открытым вопросом.

---

## 10. Versioning

Текущие versioned entities:

- `load_state_daily_v2`
- `readiness_daily`

Текущая особенность:

- `health_recovery_daily` пока не versioned отдельным полем
- для recovery breakdown используется `recovery_explanation_json`

Требование:

- при изменении формул не ломать исторические расчеты

---

## 11. Constraints

Нельзя:

- изменять raw данные
- терять ingestion history
- подменять derived state несохраняемыми эвристиками

---

## 12. Open questions

- где хранить расширенные features
- как делать массовый перерасчет
- как единообразно организовать versioning recovery layer

См. `docs/architecture/OPEN_DECISIONS.md`.

## User profile value history

`user_profile_value` (migration `011_user_profile.sql`) stores independent dated
manual inputs: `user_id`, `metric` (`ftp` or `weight`), `effective_from`, numeric
`value`, `needs_recompute`, and `updated_at`. The primary key is
`(user_id, metric, effective_from)`. Same-date saves correct an entry; unchanged
FTP saves preserve the existing pending flag without scheduling new work.
Changed FTP entries remain pending until successful recomputation. Historical
FTP values are copied from the legacy training profile without overwriting
existing entries. HealthKit records are not modified or repurposed.

See [User profile](../product/USER_PROFILE.md) for date and recompute semantics.

### Research execution metadata (#136)

`db-init/019_research_execution_metadata.sql` adds nullable
`research_experiment.execution_metadata`: a terminal-only JSON object holding
resource limits, stage exit status, timeout/OOM/cleanup flags, implementation
identities, duration and private artifact references. Existing rows remain valid;
terminal immutability is preserved. It does not hold raw inputs or predictions.
The `whatte_research_writer` NOLOGIN group has only explicit audit-column grants
and audit-sequence usage; a dedicated login is provisioned separately.
See [runner contract](../product/RESEARCH_RUNNER.md).
