# Manual physiology observations

Status: persistence/domain contract and authenticated API implemented; Telegram
and Web collection UI remain planned separately in #128 and #129.

`manual_physiology_observation_v1` stores optional user-entered physiology for
one configured local calendar date. It is raw observation storage, not a
recovery score or readiness input.

## Current observation

`manual_physiology_observation` has one current row per `(user_id, local_date)`:

| Field | Contract |
| --- | --- |
| `sleep_duration_minutes` | Optional integer, `0..1440`; zero is distinct from missing. |
| `sleep_quality` | Optional integer on the explicit `1..5` scale. |
| `hrv_ms` | Optional finite number, `> 0` and `<= 500` milliseconds. |
| `resting_hr_bpm` | Optional finite number, `20..250` bpm. |
| `source` | `telegram`, `web`, or future bounded `import`. |
| `observed_at` | Optional timezone-aware source observation timestamp. |
| `schema_version` | `manual_physiology_observation_v1`. |
| `revision` | Monotonic revision number for actual changes. |

The limits are input/storage sanity bounds, not physiology interpretation or
readiness thresholds. Nullable values represent explicit unavailability and
are never converted to zero, a neutral score, or a synthetic estimate.

`local_date` is supplied in the configured Whatte timezone. Future local dates
are rejected. `observed_at`, when present, must be timezone-aware; it is not
used to silently replace the supplied local date.

## Deterministic edits and provenance

The service serializes writes for the same user/date. On edit:

- omitted fields retain their previous value;
- explicit null clears a field;
- an identical repeat creates no revision and does not change timestamps;
- an actual value, source, or observation-time change increments `revision`.

Every change writes a full snapshot to
`manual_physiology_observation_revision`. `changed_fields`, `source`, and
`received_at` retain enough provenance to identify what a submission changed.
The revision table is append-only through the service contract.

The storage layer does not merge these observations with historical HealthKit
rows, calculate baselines, recompute readiness, or select a preferred source.
Those are separate, explicitly versioned contracts.

## API contract

The authenticated API is deliberately a thin boundary over this persistence
contract:

- `GET /api/v1/manual-physiology/{local_date}` reads one configured-user local
  date. A missing row returns `200` with `available: false` and every field as
  `unavailable`; it is never represented as poor recovery.
- `PATCH /api/v1/manual-physiology/{local_date}` accepts `source` (`telegram`
  or `web`) and any subset of value fields plus `observed_at`. Omitted fields
  retain their value; explicit `null` clears one.

Both endpoints require `Authorization: Bearer <MANUAL_PHYSIOLOGY_API_TOKEN>`.
They return field-level availability, source, observation/update timestamps,
schema version, and revision. PATCH additionally returns `changed` and
`changed_fields`; an identical repeat remains revision- and timestamp-stable.

The token is a dedicated server-side integration credential. An unset token
disables the API with `503`; it never falls back to public access. The API is
scoped to `DAILY_READINESS_USER_ID`, so clients cannot select another user.
