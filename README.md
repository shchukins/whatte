# Whatte

[Русская версия](README.ru.md)

<p align="center">
  <img src="https://img.shields.io/badge/status-active%20prototype-blue" />
  <img src="https://img.shields.io/badge/license-MIT-yellow" />
  <img src="https://img.shields.io/badge/integration-Strava-FC4C02" />
  <img src="https://img.shields.io/badge/iOS-HealthKit-black" />
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

- collects training and recovery data from Strava and Apple Health
- calculates load, recovery, and readiness in separate, traceable layers
- explains which factors influenced the result
- maps readiness to a deterministic recommendation for the day

## What it already does

- Strava activity ingestion and webhook processing
- HealthKit ingestion through the iOS client
- raw data preservation and normalized health data
- daily load and recovery models
- explainable daily readiness
- deterministic recommendation categories: `recovery`, `endurance`, `moderate`, and `high_intensity`
- compact briefing output for API, Telegram, and iOS-friendly surfaces
- a read-only internal operational dashboard

## What is planned

- a broader decision layer beyond the current readiness-to-category mapping
- calendar-aware recommendations
- recommendations for training duration and timing
- readiness calibration and explicit personalization
- continued development of the user-facing mobile application

Planned capabilities are not part of the current production baseline.

## How it works

```text
Strava + Apple Health
        ↓
load + recovery
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
- **Ecosystem independence.** Strava and Apple Health are connectors, not a hardware lock-in.
- **AI is auxiliary.** It may help with explanation and text, but it is not the calculation or decision engine.

## Current status

Whatte is an active prototype. The end-to-end backend pipeline is working: Strava and HealthKit data feed normalized health data, daily load, recovery, readiness, deterministic recommendation categories, and briefing output.

The current recommendation layer is deliberately narrow. It supports daily decision-making, but it is not yet a full training planner.

## Operational surfaces

- [`shchukin.de`](https://shchukin.de) — main web domain
- [`shchukin.de/dashboard`](https://shchukin.de/dashboard) — internal FastAPI SSR operational dashboard
- [`api.shchukin.de`](https://api.shchukin.de) — technical API domain

The dashboard shows local backend and database state for System, Connection, Ingest Jobs, and Strava Activities. It is read-only, does not call Strava or refresh tokens, and is protected at the edge with Caddy Basic Auth.

## Documentation

- [Architecture](docs/architecture/ARCHITECTURE.md)
- [Readiness model](docs/models/READINESS_MODEL.md)
- [Current state](docs/product/CURRENT_STATE.md)
- [Product scenarios](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Contributing](CONTRIBUTING.md)

## Support

Whatte is an independent open-source project. Infrastructure and development are self-funded. If you would like to support the project, [Telegram Stars](https://t.me/humanengine_lab) are welcome.
