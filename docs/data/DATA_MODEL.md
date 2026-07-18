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

---

### 4.4 `healthkit_ingest_raw`

Сырой payload HealthKit sync.

Назначение:

- воспроизводимость HealthKit ingest
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

Ключевые поля:

- `freshness`
- `recovery_score_simple`
- `readiness_score_raw`
- `readiness_score`
- `good_day_probability`
- `status_text`
- `explanation_json`
- `version`

---

### 5.9 `activity_subjective_feedback`

Слой user-reported subjective feedback.

Назначение:

- сохранить ground truth о том, как ощущалась тренировка
- сохранить ground truth о том, как ощущалось восстановление на следующий день
- отделить evaluation / calibration dataset от deterministic core calculations

Источники:

- Telegram callback после activity notification
- Telegram callback после next-day recovery prompt

Ключевые поля:

- `user_id`
- `strava_activity_id` nullable для date-level feedback
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
- новые записи пишутся с `feedback_schema_version = v1_extensible`
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
activity_subjective_feedback
```

Комментарий:

- субъективный feedback хранится отдельно от deterministic model state
- snapshot в `context_json` фиксирует состояние модели на момент ответа
- feedback не меняет upstream readiness или load tables

---

## 8. Reproducibility

Для обеспечения воспроизводимости:

- raw данные не изменяются
- normalized и derived таблицы можно пересчитать
- readiness считается из сохраненных load и recovery layers

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
