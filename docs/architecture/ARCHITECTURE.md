# Architecture

## 1. Purpose

Этот документ описывает текущую архитектуру Human Engine.

Цель:

- зафиксировать текущую структуру системы
- определить границы компонентов
- показать поток данных
- синхронизировать документацию с backend implementation

---

## 2. System overview

Human Engine построен как pipeline:

> данные -> состояние -> readiness -> решение

Высокоуровневый поток:

```text
HealthKit / Strava
↓
ingestion
↓
normalized storage
↓
load + recovery
↓
readiness
↓
decision
↓
API
↓
iOS
```

---

## 3. Deployment architecture

```text
Internet
↓
VPS (Caddy reverse proxy)
↓
Tailscale VPN
↓
Home server
↓
Backend (FastAPI)
↓
PostgreSQL
```

Свойства:

- backend не доступен напрямую из интернета
- доступ идет через VPS + Tailscale
- инфраструктура self-hosted

---

## 4. Core components

### 4.1 Backend

FastAPI сервис.

Ответственность:

- прием webhook и sync payloads
- управление ingestion pipeline
- orchestration перерасчетов
- API для доступа к данным и derived state

Backend — центр deterministic core.

---

### 4.2 Database

PostgreSQL.

Хранит:

- raw события и payloads
- normalized tables
- derived daily state
- readiness outputs

Требование:

- расчеты должны быть воспроизводимыми

---

### 4.3 Worker / orchestration paths

Фоновый процесс и orchestration endpoints.

Выполняет:

- загрузку активностей из Strava
- обработку HealthKit sync payloads
- пересчет recovery и readiness

---

## 5. Current data pipelines

### 5.1 Strava pipeline

```text
Strava
↓
Webhook event
↓
/webhook/strava
↓
strava_webhook_event
↓
strava_activity_ingest_job
↓
Worker
↓
Strava API
↓
strava_activity_raw
↓
daily_training_load
```

Свойства:

- события сохраняются
- ingestion асинхронный
- raw данные не изменяются

---

### 5.2 HealthKit full-sync pipeline

```text
HealthKit iOS
↓
POST /api/v1/healthkit/full-sync/{user_id}
↓
healthkit_ingest_raw
↓
latest raw -> normalized health tables
↓
health_recovery_daily recompute
↓
load_state_daily_v2 recompute
↓
readiness_daily recompute
↓
notification_service
```

Normalized health tables:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

Свойства:

- recompute deterministic
- `readiness_daily` materialized как daily layer
- readiness history читается из `readiness_daily` без отдельного пересчета
- на последних датах readiness должен быть непрерывным, без gaps

---

## 6. Architectural layers

### 6.1 Data layer (implemented)

- Strava ingestion
- HealthKit ingestion
- raw storage

---

### 6.2 Normalization / processing layer (implemented)

- `daily_training_load`
- HealthKit normalized tables
- recovery aggregation

Этот слой реализован в текущем backend.

---

### 6.3 Modeling layer (implemented baseline)

Ключевые таблицы:

- `health_recovery_daily`
- `load_state_daily_v2`
- `readiness_daily`

Ключевые свойства:

- load и recovery разделены на независимые контуры
- `load_state_daily_v2` считает `fitness`, `fatigue_fast`, `fatigue_slow`, `fatigue_total`, `freshness`
- расчет идет по непрерывной календарной оси
- в дни без тренировок используется `tss = 0`
- `fatigue_total` является взвешенной смесью fast/slow fatigue
- readiness считается из load state и recovery state, а не только из freshness
- readiness является финальной агрегированной метрикой текущего state layer
- `good_day_probability` хранится как отдельный probability layer

---

### 6.4 Decision layer (implemented)

Decision layer consumes `readiness_daily` output and produces deterministic user-facing guidance.

Implemented outputs:

- `recommendation`
- `reason`
- deterministic readiness briefing

Current mapping:

- `< 40` -> `recovery`
- `40 <= score < 60` -> `endurance`
- `60 <= score <= 75` -> `moderate`
- `> 75` -> `high_intensity`

Current flow:

```text
HealthKit
↓
ingestion
↓
normalized health tables
↓
health_recovery_daily
↓
load_state_daily_v2
↓
readiness_daily
↓
decision_engine
↓
readiness API
↓
iOS Today screen
```

Важно:

- decision layer не пересчитывает readiness formula
- decision layer не использует ML или LLM
- `notification_service` использует `readiness_daily`
- notification layer использует deterministic readiness briefing как основной комментарий

---

### 6.5 Evaluation / calibration layer (implemented as storage, not as model loop)

Current table:

- `activity_subjective_feedback`

Role:

- collect user-reported outcomes after training and recovery
- preserve historical recommendation/readiness context at feedback time
- support later validation and calibration work

Properties:

- does not modify deterministic load / recovery / readiness logic
- supports both activity-level and date-level feedback
- uses normalized fields for queries, extensible payload for type-specific context, and `context_json` for historical model snapshots
- remains outside the core state calculation path

High-level relationship:

```text
raw inputs -> derived state -> readiness -> recommendation
                                  |
                                  v
                    subjective feedback / ground truth capture
```

This layer is intentionally append-only in meaning:

- the system predicts first
- the athlete reports outcome later
- future calibration compares the two without rewriting the original state

---

## 7. Observability

Текущий backend использует structured JSON logging.

Ключевые события:

- `api_request_started`
- `api_request_finished`
- `healthkit_full_sync_started`
- `healthkit_full_sync_finished`
- `readiness_recompute_started`
- `readiness_recompute_finished`

Для наблюдаемости используются Grafana и Loki:

- Loki хранит и индексирует JSON logs
- Grafana используется для поиска событий, таймлайнов и operational checks

---

## 8. Core vs AI boundary

### Core

- backend
- database
- ingestion
- normalization
- domain logic
- readiness logic

Свойства:

- deterministic
- воспроизводимый
- проверяемый

---

### AI

- RAG
- LLM
- генерация текста

Свойства:

- не влияет на расчеты
- не участвует в принятии решений
- работает отдельно от core

---

## 9. Architecture principles

### Deterministic first

- логика должна быть явной
- одинаковый вход -> одинаковый результат

---

### Simplicity over complexity

- простые решения предпочтительнее
- избегать лишних абстракций

---

### Reproducibility

- любой расчет можно повторить
- raw данные сохраняются

---

### Separation of concerns

- source ingestion, normalization, model and decision разделены
- load и recovery не смешиваются в один неявный сигнал
- AI не смешивается с core

---

## 10. Current model v2 baseline

Текущая product-level схема:

```text
LoadState + RecoveryState -> Readiness -> GoodDayProbability
```

Где:

- `LoadState` описывает тренировочную нагрузку
- `RecoveryState` описывает восстановление организма
- `Readiness` является отдельным слоем, а не полем внутри load state

---

## 11. Evolution path

Текущее состояние:

- ingestion pipelines
- raw storage
- normalized health layer
- recovery layer
- load model v2 baseline
- readiness baseline
- decision layer
- readiness API
- iOS Today screen
- HealthKit auto sync

---

## 12. Constraints

Нельзя:

- внедрять AI в core
- скрывать логику
- подменять load/recovery контуры текстовой эвристикой
- менять доменный смысл без явной фиксации

Можно:

- упрощать
- делать логику явной
- улучшать наблюдаемость

---

## 13. Consistency rule

Любое изменение должно:

- вписываться в pipeline
- не ломать границы между слоями
- явно отделять implemented behavior от несуществующего behavior

Если компонент не вписывается:

- либо он лишний
- либо архитектура нарушена
