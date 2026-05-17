# Human Engine

[Русская версия](README.ru.md)

<p align="center">
  <img src="https://img.shields.io/badge/status-active%20prototype-blue" />
  <img src="https://img.shields.io/badge/license-MIT-yellow" />
  <img src="https://img.shields.io/badge/integration-Strava-FC4C02" />
  <img src="https://img.shields.io/badge/iOS-HealthKit-black" />
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

**Morning readiness briefing** — every morning you get your recovery state, training load trend, and a concrete recommendation for the day. Not a score. An answer.

**Adaptive training suggestion** — the system knows your calendar, your available time, and your current readiness. It suggests a workout that fits your actual day — duration, intensity, timing.

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

Active prototype. Core pipeline is working end-to-end — readiness is computed daily from real Strava and HealthKit data, delivered to iOS. Product features are in active development.

---

## Documentation

- [Architecture](docs/architecture/ARCHITECTURE.md)
- [Readiness model](docs/models/READINESS_MODEL.md)
- [Current state](docs/product/CURRENT_STATE.md)
- [Product scenarios](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Contributing](CONTRIBUTING.md)
