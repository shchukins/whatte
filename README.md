# Human Engine

[English version](README.en.md)

<p align="center">
  <img src="https://img.shields.io/badge/status-experimental-blue" />
  <img src="https://img.shields.io/badge/license-MIT-yellow" />
  <img src="https://img.shields.io/badge/core-deterministic-green" />
  <img src="https://img.shields.io/badge/backend-FastAPI-009688" />
  <img src="https://img.shields.io/badge/database-PostgreSQL-336791" />
  <img src="https://img.shields.io/badge/iOS-HealthKit-black" />
  <img src="https://img.shields.io/badge/integration-Strava-FC4C02" />
</p>

<p align="center">
  Детерминированная система для расчета тренировочной нагрузки, восстановления и readiness.
</p>

<p align="center">
  <code>signal → load state + recovery state → readiness → decision support</code>
</p>

## Идея

Human Engine не является ни тренировочным дневником, ни AI-коучем.
Это инженерная система, которая принимает source data, строит state layers и выдает воспроизводимые readiness outputs.

## Что уже реализовано

- FastAPI backend
- PostgreSQL
- Strava ingestion
- HealthKit raw ingest и full sync orchestration
- raw storage для Strava и HealthKit payloads
- HealthKit normalized tables
- `daily_training_load`
- `health_recovery_daily`
- `load_state_daily_v2`
- `readiness_daily`
- `activity_subjective_feedback`
- readiness history endpoint
- structured JSON logging
- Grafana + Loki observability
- iOS auto sync через `SyncCoordinator`
- iOS Today screen с readiness, explanation, recommendation и 7-day trend

## Текущий baseline

- модель: `LoadState + RecoveryState -> Readiness -> GoodDayProbability`
- readiness считается ежедневно и хранится в `readiness_daily`
- readiness history читается из уже сохраненных rows
- readiness history должен быть непрерывным, без gaps на последних датах
- `good_day_probability = readiness_score / 100`
- readiness не равен freshness

Fallback modes:

- full: есть load и recovery
- `recovery_only`: есть только recovery
- `load_only`: есть только load
- `no_data`: `404`, row не создается

## Текущий pipeline

```text
HealthKit / Strava
        |
        v
raw ingest
        |
        v
normalized tables
        |
        v
health_recovery_daily
        |
        v
load_state_daily_v2
        |
        v
readiness_daily
        |
        v
history endpoint
        |
        v
iOS Today screen
```

Ключевые свойства:

- recompute deterministic
- readiness history endpoint не делает recompute
- trend UI читает последние readiness points в ascending date order
- post-ride Telegram RPE feedback сохраняется отдельно и не меняет deterministic расчеты

## API

Основные readiness endpoints:

- `POST /api/v1/model/readiness-daily/{user_id}/{date}`
- `GET /api/v1/model/readiness-daily/{user_id}/history?days=7`
- `POST /api/v1/healthkit/full-sync/{user_id}`

History endpoint:

- читает `readiness_daily`
- не пересчитывает readiness
- возвращает последние `N` точек в порядке возрастания даты

Подробнее: [docs/api/READINESS_API.md](docs/api/READINESS_API.md)

## Observability

Backend пишет structured JSON logs.

Основные события:

- `api_request_started`
- `api_request_finished`
- `healthkit_full_sync_started`
- `healthkit_full_sync_finished`
- `readiness_recompute_started`
- `readiness_recompute_finished`
- `feedback_received`
- `feedback_updated`
- `feedback_invalid_callback`

Подробнее: [docs/architecture/OBSERVABILITY.md](docs/architecture/OBSERVABILITY.md)

## Принципы

- deterministic core first
- простая и явная логика
- воспроизводимость расчетов
- load и recovery остаются раздельными контурами
- AI является вспомогательным слоем, а не ядром продукта

## Структура репозитория

```text
backend/        backend service
backend/infra/  local infrastructure
db-init/        database initialization
compose.yaml    deployment
docs/           documentation
```

## Основные документы

- [docs/models/READINESS_MODEL.md](docs/models/READINESS_MODEL.md)
- [docs/models/SUBJECTIVE_FEEDBACK.md](docs/models/SUBJECTIVE_FEEDBACK.md)
- [docs/models/model_v2_architecture.md](docs/models/model_v2_architecture.md)
- [docs/api/READINESS_API.md](docs/api/READINESS_API.md)
- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)
- [docs/architecture/OBSERVABILITY.md](docs/architecture/OBSERVABILITY.md)
- [docs/product/SCENARIOS.md](docs/product/SCENARIOS.md)
- [docs/product/CURRENT_STATE.md](docs/product/CURRENT_STATE.md)
- [backend/README.md](backend/README.md)
- [AGENTS.md](AGENTS.md)

## Статус

Экспериментальный проект с детерминированным product core, стабилизированным readiness v2 baseline и работающим auto-sync MVP.
