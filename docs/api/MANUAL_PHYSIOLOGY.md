# Manual physiology API

## Purpose

These authenticated endpoints expose the persisted optional manual physiology
observation as the shared backend source of truth for Telegram and Web. They
store raw observations only; they do not calculate baselines, recovery, or
readiness and do not trigger recomputation.

## Authentication and scope

Every request requires:

```text
Authorization: Bearer <MANUAL_PHYSIOLOGY_API_TOKEN>
```

If the server token is not configured, the API returns `503`; a missing or
incorrect credential returns `401`. The API is always scoped to the server's
`DAILY_READINESS_USER_ID`, not to a user ID supplied by the client.

## Read one local date

```text
GET /api/v1/manual-physiology/{local_date}
```

`local_date` is an ISO local calendar date. Missing data returns `200` rather
than `404` so a client can render it as unavailable. Each `fields` item has
`availability: available|unavailable` and a nullable `value`. Responses also
include source, timestamps, schema version, and revision when a row exists.

## Create or update one local date

```text
PATCH /api/v1/manual-physiology/{local_date}
Content-Type: application/json
```

Example:

```json
{
  "source": "web",
  "sleep_duration_minutes": 450,
  "hrv_ms": 54.2,
  "observed_at": "2026-10-01T06:10:00+03:00"
}
```

Allowed fields are `sleep_duration_minutes` (`0..1440`), `sleep_quality`
(`1..5`), `hrv_ms` (`>0..500`), `resting_hr_bpm` (`20..250`), and optional
timezone-aware `observed_at`. `source` is `telegram` or `web`.

The date cannot be in the configured Whatte timezone's future. Omitted fields
are not changed; explicit `null` clears a field. Invalid fields receive
FastAPI's deterministic field-level `422` response. The response reports
`changed` and `changed_fields`; sending an identical submission returns
`changed: false` and creates no revision.

## Protected Web Today adapter

Web Today reads/writes the same models and persistence service through its
server-side `/today` routes, like the Telegram adapter. Browsers submit
URL-encoded `POST /today/physiology` forms under existing Caddy Basic Auth and
cross-site request checks; the Bearer token is never embedded in HTML or JS.
The form supplies the rendered local date, optional numeric values and explicit
`clear_<field>=1` actions. Empty controls are omitted; Clear overrides a supplied
value with null. The backend fixes `source=web` and the configured user.

Successful writes redirect with `303` to `/today?saved=physiology`. Invalid or
empty submissions render `422` with retained input; stale-day forms render `409`
and request a reload; write failures render `503` without claiming success.
This adapter does not change authentication or responses on the GET/PATCH API.
