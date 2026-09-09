# Architecture

## 1. Purpose

Этот документ описывает текущую архитектуру Whatte.

Цель:

- зафиксировать текущую структуру системы
- определить границы компонентов
- показать поток данных
- синхронизировать документацию с backend implementation

---

## 2. System overview

Whatte построен как pipeline:

> данные -> состояние -> readiness -> решение

Высокоуровневый поток:

```text
Strava + Web/Telegram feedback
↓
ingestion
↓
normalized storage
↓
load + freshness + response + feeling
↓
readiness (+ exact-date historical physiology when available)
↓
decision
↓
API / Web Today / Telegram
```

---

## 3. Deployment architecture

```text
Internet
↓
VPS (Caddy reverse proxy)
↓
Backend (FastAPI)
↓
PostgreSQL
```

Свойства:

- production backend работает на VPS
- Caddy завершает TLS и проксирует публичные домены на локальный FastAPI upstream
- инфраструктура self-hosted
- `shchukin.de` используется для web surfaces
- `shchukin.de/dashboard` проксируется на backend как internal SSR dashboard
- `api.shchukin.de` остается техническим API-доменом для Strava webhook, health, OAuth, and model paths
- старый home-server deployment / watchdog monitoring является legacy context, а не текущей основной production-схемой

---

## 4. Core components

### 4.1 Backend

FastAPI сервис.

Backend serves three distinct surface families through the same application process:

- technical API endpoints on `api.shchukin.de`
- internal SSR dashboard at `shchukin.de/dashboard`
- protected Web Today and dated-profile forms at `shchukin.de/today`

Ответственность:

- прием webhook и sync payloads
- управление ingestion pipeline
- orchestration перерасчетов
- API для доступа к данным и derived state

Backend — центр deterministic core.

Dashboard implementation constraints:

- server-side rendered HTML via FastAPI + Jinja2
- templates under `backend/backend/templates/dashboard/`
- dashboard modules under `backend/backend/dashboard/`
- minimal CSS only
- no SPA and no frontend build step
- protected at the edge with `Caddy` Basic Auth
- Google OAuth remains a future authorization improvement

Current dashboard is operational and read-only:

- `System`: backend status, database health via `get_conn()` + `SELECT 1`, server time, process start time, uptime, and database error fallback
- `Connection`: Strava connection status, athlete id, scope, token expiry, and token state
- `Ingest Jobs`: latest jobs plus pending and failed/error counts
- `Strava Activities`: latest saved local activities and total count

Dashboard boundaries:

- reads local backend/database state only
- does not call Strava API
- does not refresh tokens
- does not mutate database state
- does not show raw payloads, access tokens, refresh tokens, or secrets
- one section failure must not break all of `/dashboard`

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
- scheduled local-day load/readiness recompute
- отправку daily readiness briefing

---

### 4.4 Notification and feedback orchestration

Backend-owned orchestration now also covers Telegram feedback collection workflows.

Current responsibilities:

- daily readiness delivery
- post-ride RPE prompt delivery
- scheduled next-day recovery prompt delivery
- callback ingestion for subjective feedback
- prompt idempotency and delivery logging

Important boundary:

- orchestration decides when to send already-defined prompts
- deterministic readiness and recovery calculations remain upstream and unchanged

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

### 5.2 Daily readiness pipeline

```text
configured local target date
↓
load_state_daily_v2 recompute through target date
↓
response + feeling + optional exact-date historical physiology
↓
readiness_daily recompute
↓
persisted readiness briefing contract -> Web Today / Telegram
```

Preserved historical tables:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

Свойства:

- HealthKit collection routes and the iOS client are retired
- historical rows are not deleted or carried forward to a later date
- recompute remains deterministic
- `readiness_daily` materialized как daily layer
- readiness history читается из `readiness_daily` без отдельного пересчета
- на последних датах readiness должен быть непрерывным, без gaps
- `decision_engine.build_persisted_readiness_briefing` строит единственный
  recommendation/reason/briefing contract из materialized current-version
  readiness; delivery surfaces не выводят synthetic readiness из load state

---

## 6. Architectural layers

### 6.1 Data layer (implemented)

- Strava ingestion
- Web/Telegram feedback ingestion
- raw storage

---

### 6.2 Normalization / processing layer (implemented)

- `daily_training_load`
- preserved historical HealthKit normalized tables
- historical recovery aggregation for deliberate replay

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
- readiness composes freshness, response, feeling, and optional exact-date physiology
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
Strava load + response + feeling
↓
readiness_daily
↓
decision_engine
↓
readiness API / Web Today / Telegram
```

Важно:

- decision layer не пересчитывает readiness formula
- decision layer не использует ML или LLM
- `notification_service` is orchestration only and consumes the canonical
  persisted readiness briefing contract

---

### 6.5 Evaluation / calibration layer (implemented as storage, not as model loop)

Current tables:

- `activity_subjective_feedback`
- `decision_context_snapshot`

Role:

- collect user-reported outcomes after training and recovery
- preserve historical recommendation/readiness context at feedback time
- support later validation and calibration work

Properties:

- does not modify deterministic load / recovery / readiness logic
- supports both activity-level and date-level feedback
- uses normalized fields for queries, extensible payload for type-specific context, and `context_json` for historical model snapshots
- preserves delivery and recovery-check-in decision boundaries as append-only,
  idempotent snapshots for pilot reporting and later calibration joins
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
- `readiness_recompute_started`
- `readiness_recompute_finished`

Для наблюдаемости используются Grafana и Loki:

- Loki хранит и индексирует JSON logs
- Grafana используется для поиска событий, таймлайнов и operational checks

Operational monitoring hierarchy:

- FastAPI SSR dashboard at `shchukin.de/dashboard` is the primary current operational monitoring surface for production state
- Grafana/Loki remains the lower-level log analysis stack
- old home-server Telegram watchdog / cron monitoring is legacy and should not be treated as primary production monitoring

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
LoadState + Response + Feeling + optional Physiology -> Readiness -> GoodDayProbability
```

Где:

- `LoadState` описывает тренировочную нагрузку
- `Response` и `Feeling` дают wearable-independent recovery evidence
- optional historical `Physiology` обогащает только совпадающую дату
- `Readiness` является отдельным слоем, а не полем внутри load state

---

## 11. Evolution path

Текущее состояние:

- Strava and feedback ingestion pipelines
- raw storage
- normalized health layer
- recovery layer
- load model v2 baseline
- readiness baseline
- decision layer
- readiness API
- Web Today surface
- scheduled daily readiness orchestration
- preserved historical HealthKit storage with no active collection

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

## 14. Recovery prompt scheduling flow

```text
worker loop
↓
UTC hour gate (`NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC`)
↓
candidate users from previous-day load/activity
↓
feedback exists? -> skip
↓
prompt log claim in `subjective_feedback_prompt_log`
↓
Telegram send
↓
prompt log update (`sent` / `failed`)
↓
Telegram callback -> `activity_subjective_feedback` upsert
```

This keeps orchestration state separate from the deterministic model state and from the eventual subjective outcome row.
