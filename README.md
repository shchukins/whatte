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

**WHATTE — Adaptive Training Decision Engine.**

The product direction is to help choose today's most useful workout given a
long-term goal, completed training and the time actually available across the week.

## The problem

A plan calls for a two-hour endurance ride, but only 50 minutes remain.
Shorten, replace, reschedule or rest? WHATTE should explain the compromise and
help preserve the purpose of the training week. More TSS or higher readiness
alone does not establish better training progress.

## What it already does

The current prototype ingests Strava activities and Web/Telegram feedback,
calculates load, response and readiness, and produces deterministic categories
`recovery`, `endurance`, `moderate` and `high_intensity` with a shared briefing.
It includes a dated profile, RPE guidance/history, Today/Diary and a read-only
operational dashboard. Historical HealthKit rows are preserved; collection and
the iOS client are retired. Optional manual physiology is a separate research path.

The readiness category remains unchanged. Today also uses the deterministic
`training_time_policy_v1` with a saved manual block priority, weekly plan, activity
facts and confirmed time windows. Changing today’s available minutes produces
a proposal with stimulus tradeoffs and alternatives; it never applies plan changes.
Permissions and compatibility reviews are explicit. Acceptance and activity-to-plan
linkage remain planned. This is not a complete coach or automated planner.

## Next experiment — planned

One cyclist, one block, a manual plan, and available time as the first changing
constraint. Simple rules compare shortening, replacement, rescheduling and rest,
explain preserved/lost stimulus, and propose any weekly-plan changes.
See the [bounded MVP](docs/product/TRAINING_DECISION_MVP.md).

Success means useful decisions when circumstances change and observed progress
on agreed comparable tasks. Plan compliance and load-model `fitness` are not
proof of improved sporting capability; one block cannot establish WHATTE's effect.

## Priorities

Readiness/recovery remain supporting context. Expansion of HRV/RHR/sleep models,
recovery prediction and autoresearch is paused as a development priority;
calibration does not block the first experiment. This decision does not alter
running processes or stored data.

## Principles

- Deterministic core and backend-owned decisions.
- Explained tradeoffs, versioned rules and reproducibility.
- Explicit missingness; missing data is not good recovery.
- No required wearable, LLM or mobile application.
- Simple rules and comparison to a simple baseline before further complexity.

## Operational surfaces

- [`shchukin.de`](https://shchukin.de) — main web domain
- [`shchukin.de/dashboard`](https://shchukin.de/dashboard) — internal FastAPI SSR operational dashboard
- [`api.shchukin.de`](https://api.shchukin.de) — technical API domain

The dashboard shows local backend and database state for System, Connection, Ingest Jobs, and Strava Activities. It is read-only, does not call Strava or refresh tokens, and is protected at the edge with Caddy Basic Auth.

## Documentation

- [Product direction](docs/ai/PRODUCT_CONTEXT.md)
- [Current priorities](docs/ai/CURRENT_PRIORITIES.md)
- [Training decision MVP](docs/product/TRAINING_DECISION_MVP.md)

- [Architecture](docs/architecture/ARCHITECTURE.md)
- [Readiness model](docs/models/READINESS_MODEL.md)
- [Training response](docs/models/TRAINING_RESPONSE.md)
- [Current state](docs/product/CURRENT_STATE.md)
- [Product scenarios](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Versioned SQL migrations](docs/data/MIGRATIONS.md)
- [Immutable application releases](ops/releases/README.md)
- [Centralized production delivery and verified issue lifecycle](ops/deploy/README.md)
- [Contributing](CONTRIBUTING.md)
- [Git workflow and optional PRs](docs/ai/rules/PR_WORKFLOW_RULES.md)
