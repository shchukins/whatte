# Observability

## 1. Overview

Observability в Whatte нужен не как отдельный продуктовый слой, а как способ видеть работу deterministic core.

Цели:

- понимать, какие pipeline steps были выполнены
- проверять воспроизводимость backend behavior
- объяснять, почему система пришла к конкретному состоянию
- быстро находить ошибки ingestion, recompute и API paths

Принципы:

- deterministic: события отражают фактические шаги системы
- reproducible: логи помогают восстановить последовательность обработки
- explainable: ключевые решения backend видны через structured events

---

## 2. Logging Architecture

Backend пишет structured JSON logs в stdout. Docker сохраняет stdout как docker logs. Promtail читает docker logs, парсит JSON payload и отправляет записи в Loki. Grafana использует Loki как datasource для анализа.

```text
Backend (JSON logs)
        |
        v
Docker logs
        |
        v
Promtail (docker + json parsing)
        |
        v
Loki
        |
        v
Grafana
```

Observability stack находится в `infra/monitoring/observability` и не меняет deterministic backend logic.

---

## 3. Structured Logging

Backend logs are JSON objects.

Required fields:

- `timestamp`
- `level`
- `service`
- `event`

Common additional fields:

- `user_id`
- `request_id`
- `path`
- `duration_ms`
- `job_id`
- `activity_id`

Example:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "service": "human-engine-backend",
  "event": "readiness_recompute_finished",
  "user_id": "sergey",
  "readiness_score": 56.1
}
```

The `event` field is the main unit of observability. Logs should describe system events, not free-form text lines.

---

## 4. Events

Key events currently used by the backend:

API:

- `api_request_started`
- `api_request_finished`

HealthKit:

- `healthkit_full_sync_started`
- `healthkit_full_sync_finished`
- `healthkit_payload_processed`

Readiness:

- `readiness_recompute_started`
- `readiness_recompute_finished`

Errors:

- `error`

Error events include context fields such as `error_type`, `error`, `context`, `path`, `request_id`, and `user_id` when available.

---

## 5. Promtail Pipeline

Promtail pipeline:

- `docker` stage unwraps Docker log records
- `json` stage parses backend JSON payload
- `labels` stage promotes only stable fields:
  - `service`
  - `event`
  - `level`

`user_id` is intentionally not a label.

Reason: label values create Loki streams. User-specific labels increase cardinality and make storage and queries more expensive. Use `user_id` as a parsed JSON field in LogQL queries instead.

---

## 6. Operational Surfaces

The current primary production monitoring surface is the FastAPI SSR dashboard at `https://shchukin.de/dashboard`.

It shows high-level production state:

- System status
- Strava connection/token state
- ingest job status
- latest locally stored Strava activities

Dashboard constraints:

- read-only
- local backend/database state only
- no external Strava API calls
- no token refresh
- no database mutations
- no secrets or raw payloads
- one section failure must not break the whole page

Grafana/Loki remains the lower-level log analysis view for backend behavior.

Panels:

- event volume: shows how many structured events are produced over time; answers "is the system active?"
- durations: shows request or job durations; answers "what became slower?"
- errors: shows `event="error"` records; answers "what failed and where?"
- HealthKit sync: shows full-sync start/finish and payload processing; answers "did sync run and complete?"
- readiness recompute: shows readiness recompute events; answers "was readiness recalculated?"
- pipeline trace: shows ordered events for a user, request, or job; answers "what happened in this processing path?"

Both dashboard surfaces are for analysis and operations. They should not become a source of product logic.

Legacy note:

- old home-server Telegram watchdog / cron monitoring is no longer the primary production monitoring channel
- Telegram alerts may still exist as auxiliary notifications, but they are not the main monitoring strategy right now

---

## 7. How to Debug

Find all events for a user:

```logql
{service="human-engine-backend"} | json | user_id="sergey"
```

Check readiness recompute:

```logql
{service="human-engine-backend", event="readiness_recompute_finished"}
```

Check errors:

```logql
{service="human-engine-backend", event="error"}
```

Trace one API request:

```logql
{service="human-engine-backend"} | json | request_id="..."
```

Check slow API requests:

```logql
{service="human-engine-backend", event="api_request_finished"} | json | duration_ms > 1000
```

---

## 8. Design Principles

- Do not log everything.
- Log events, not arbitrary strings.
- Keep labels minimal and stable.
- Keep domain calculations outside observability.
- Prefer readable logs over exhaustive logs.
- Add fields only when they help debug a real system path.
