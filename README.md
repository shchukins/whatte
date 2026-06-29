# Human Engine

[Русская версия](README.ru.md)

<p align="center">
  <img src="https://img.shields.io/badge/статус-активный%20прототип-blue" />
  <img src="https://img.shields.io/badge/лицензия-MIT-yellow" />
  <img src="https://img.shields.io/badge/интеграция-Strava-FC4C02" />
  <img src="https://img.shields.io/badge/iOS-HealthKit-black" />
  <a href="https://t.me/humanengine_lab">
    <img src="https://img.shields.io/badge/Telegram-Human%20Engine-2CA5E0?logo=telegram" />
  </a>
</p>

<p align="center">
  <strong>Train around your life, not around a plan.</strong>
</p>

---

## Why Human Engine

Most training platforms assume you live for training. You adjust your sleep, your work, your weekends — to fit the plan. Human Engine flips this.

It reads your recovery, looks at your day, and tells you what kind of training makes sense *right now* — not what the template says.

---

## Your ecosystem, your data

You don't need Garmin to get Garmin-quality load analysis. Human Engine works with whatever you already use — Wahoo, Zwift, Rouvy, Apple Watch, any trainer that exports to Strava. No ecosystem lock-in. No hardware requirements.

Strava and Apple Health are the connectors. Everything else is yours.

---

## What it does

**Morning readiness briefing** — the backend already produces a daily readiness result with explanation, a deterministic recommendation zone, and Telegram/iOS-friendly briefing text.

**Deterministic training guidance** — the current product maps readiness into explicit training guidance like `recovery`, `endurance`, `moderate`, or `high_intensity`. Broader day-planning logic such as calendar-aware timing or duration selection remains planned.

**Explainable outputs** — every recommendation shows its reasoning. HRV down, sleep short, high fatigue — you see exactly why. No black box.

---

## How it works

```
Strava + Apple Health
        ↓
load model + recovery model
        ↓
readiness score + explanation
        ↓
training recommendation
        ↓
morning briefing
```

The core is deterministic and reproducible. AI is an auxiliary layer, not the product — every output can be traced back to a formula and a data point.

---

## Principles

- your data stays yours — self-hosted, no third-party cloud
- deterministic core: same inputs always produce the same outputs
- explainability over accuracy theatre — know why, not just what
- ecosystem-agnostic: works with any hardware that talks to Strava or Apple Health

---

## Status

Active prototype. Core pipeline is working end-to-end: Strava and HealthKit data flow into daily load, recovery, readiness, and deterministic recommendation outputs. Daily readiness is available through the API and Telegram delivery. Broader planning and calibration work remain in active development.

## Operational Surfaces

- `shchukin.de` is the main web domain for user/admin web surfaces.
- `shchukin.de/dashboard` serves the internal dashboard as a FastAPI server-side rendered HTML page.
- `api.shchukin.de` remains the technical API domain for FastAPI endpoints, Strava OAuth callback, Telegram webhook, HealthKit sync, `/healthz`, and API docs when enabled.

Current dashboard implementation:

- FastAPI SSR route: `/dashboard`
- Jinja2 templates with minimal CSS
- no SPA and no frontend build step
- current sections: System, Strava placeholder, Ingest Jobs placeholder, Connection placeholder, System Info placeholder

Security note:

- the internal dashboard is not yet production-secure
- the next required protection step is `Caddy` Basic Auth for `/dashboard`
- a later option is Google OAuth restricted to a single allowed user email

---

## Documentation

- [Architecture](docs/architecture/ARCHITECTURE.md)
- [Readiness model](docs/models/READINESS_MODEL.md)
- [Current state](docs/product/CURRENT_STATE.md)
- [Product scenarios](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Contributing](CONTRIBUTING.md)

## Support

Human Engine is an independent open-source project. Infrastructure and development are self-funded — if you'd like to help, Telegram Stars are welcome.
