# Human Engine

[Русская версия](README.md)

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
  A deterministic system for training load, recovery, and readiness computation.
</p>

<p align="center">
  <code>signal → load state + recovery state → readiness → decision support</code>
</p>

## Idea

Human Engine is neither a training log nor an AI coach.
It is an engineering system that ingests source data, builds state layers, and returns reproducible readiness outputs.

## Implemented

- FastAPI backend
- PostgreSQL
- Strava ingestion
- HealthKit raw ingest and full sync orchestration
- raw storage for Strava and HealthKit payloads
- HealthKit normalized tables
- `daily_training_load`
- `health_recovery_daily`
- `load_state_daily_v2`
- `readiness_daily`
- readiness history endpoint
- structured JSON logging
- Grafana + Loki observability
- iOS auto sync via `SyncCoordinator`
- iOS Today screen with readiness, explanation, recommendation, and 7-day trend

## Current baseline

- model: `LoadState + RecoveryState -> Readiness -> GoodDayProbability`
- readiness is computed daily and stored in `readiness_daily`
- readiness history reads already stored rows
- readiness history should be continuous, with no gaps on recent dates
- `good_day_probability = readiness_score / 100`
- readiness is not equal to freshness

Fallback modes:

- full: both load and recovery are available
- `recovery_only`: only recovery is available
- `load_only`: only load is available
- `no_data`: `404`, no row is created

## Current pipeline

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

Key properties:

- deterministic recompute
- the readiness history endpoint does not recompute
- the trend UI reads the latest readiness points in ascending date order

## API

Main readiness endpoints:

- `POST /api/v1/model/readiness-daily/{user_id}/{date}`
- `GET /api/v1/model/readiness-daily/{user_id}/history?days=7`
- `POST /api/v1/healthkit/full-sync/{user_id}`

History endpoint:

- reads `readiness_daily`
- does not recompute readiness
- returns the latest `N` points in ascending date order

See: [docs/api/READINESS_API.md](docs/api/READINESS_API.md)

## Observability

The backend writes structured JSON logs.

Main events:

- `api_request_started`
- `api_request_finished`
- `healthkit_full_sync_started`
- `healthkit_full_sync_finished`
- `readiness_recompute_started`
- `readiness_recompute_finished`

See: [docs/architecture/OBSERVABILITY.md](docs/architecture/OBSERVABILITY.md)

## Principles

- deterministic core first
- simple and explicit logic
- reproducible calculations
- load and recovery stay separate contours
- AI is an auxiliary layer, not the product core

## Repository structure

```text
backend/        backend service
backend/infra/  local infrastructure
db-init/        database initialization
compose.yaml    deployment
docs/           documentation
```

## Main documents

- [docs/models/READINESS_MODEL.md](docs/models/READINESS_MODEL.md)
- [docs/models/model_v2_architecture.md](docs/models/model_v2_architecture.md)
- [docs/api/READINESS_API.md](docs/api/READINESS_API.md)
- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)
- [docs/architecture/OBSERVABILITY.md](docs/architecture/OBSERVABILITY.md)
- [docs/product/SCENARIOS.md](docs/product/SCENARIOS.md)
- [docs/product/CURRENT_STATE.md](docs/product/CURRENT_STATE.md)
- [backend/README.md](backend/README.md)
- [AGENTS.md](AGENTS.md)

## Status

Experimental project with a deterministic product core, a stabilized readiness v2 baseline, and a working auto-sync MVP.
