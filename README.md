# Whatte

[Русская версия](README.ru.md)

<p align="center">
  <img src="https://img.shields.io/badge/status-active%20prototype-blue" />
  <img src="https://img.shields.io/badge/license-MIT-yellow" />
  <img src="https://img.shields.io/badge/integration-Strava-FC4C02" />
  <a href="https://t.me/humanengine_lab">
    <img src="https://img.shields.io/badge/Telegram-Whatte-2CA5E0?logo=telegram" />
  </a>
</p>

<p align="center">
  <strong>What today?</strong>
</p>

Whatte is an application and backend system that combines training load, recovery, and user context to help answer a practical daily question: should today be for high intensity, easy training, recovery, or rest?

## The problem

Static training plans cannot account for real life. Sleep, work, fatigue, and previous sessions change what the body is ready for, even when the calendar says otherwise.

The useful question is not only what the plan prescribed, but what load is appropriate today.

## Whatte's answer

Whatte:

- collects training data from Strava and subjective recovery feedback from Web/Telegram
- calculates load, recovery, and readiness in separate, traceable layers
- explains which factors influenced the result
- maps readiness to a deterministic recommendation for the day

## What it already does

- Strava activity ingestion and webhook processing
- preserved historical HealthKit data as optional exact-date physiology evidence
- daily load and recovery models
- versioned training-response metrics and personal comparable-session baselines
- explainable daily readiness
- deterministic recommendation categories: `recovery`, `endurance`, `moderate`, and `high_intensity`
- compact briefing output for API, Telegram, and Web Today
- a read-only internal operational dashboard

## What is planned

- a broader decision layer beyond the current readiness-to-category mapping
- calendar-aware recommendations
- recommendations for training duration and timing
- readiness calibration and explicit personalization

Planned capabilities are not part of the current production baseline.

## How it works

```text
Strava + subjective feedback + optional historical physiology
        ↓
load + freshness + response + feeling + optional physiology
        ↓
readiness
        ↓
deterministic recommendation
        ↓
daily briefing
```

## Principles

- **Deterministic core.** The same inputs produce the same result.
- **Explainability.** Recommendations can be traced to data, metrics, and rules.
- **Reproducibility.** Raw inputs are preserved and derived state can be recomputed.
- **Ecosystem independence.** The core daily loop does not require a wearable or mobile application.
- **AI is auxiliary.** It may help with explanation and text, but it is not the calculation or decision engine.

## Current status

Whatte is an active prototype. The end-to-end backend pipeline is working from Strava load, activity response, subjective feeling, optional exact-date historical physiology, readiness, deterministic recommendation categories, and briefing output. HealthKit collection and the iOS client are retired; stored historical records remain intact.

The current recommendation layer is deliberately narrow. It supports daily decision-making, but it is not yet a full training planner.

## Operational surfaces

- [`shchukin.de`](https://shchukin.de) — main web domain
- [`shchukin.de/dashboard`](https://shchukin.de/dashboard) — internal FastAPI SSR operational dashboard
- [`api.shchukin.de`](https://api.shchukin.de) — technical API domain

The dashboard shows local backend and database state for System, Connection, Ingest Jobs, and Strava Activities. It is read-only, does not call Strava or refresh tokens, and is protected at the edge with Caddy Basic Auth.

## Documentation

- [Architecture](docs/architecture/ARCHITECTURE.md)
- [Readiness model](docs/models/READINESS_MODEL.md)
- [Training response](docs/models/TRAINING_RESPONSE.md)
- [Current state](docs/product/CURRENT_STATE.md)
- [Product scenarios](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Contributing](CONTRIBUTING.md)
