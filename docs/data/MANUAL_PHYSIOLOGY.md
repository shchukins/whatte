# Manual physiology observations

Status: persistence/domain contract, authenticated API, and optional Telegram
collection implemented; Web collection UI remains planned separately in #129.

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

## Personal-relative features

`personal_physiology_feature_daily` is the manual-observation-only derived
contract for research and future feature vectors. It does not use HealthKit,
does not calculate a synthetic recovery score, and is not a readiness input.

Version `personal_physiology_features_v1` uses the preceding 28 calendar days,
excluding the target date, and requires seven non-null earlier observations per
signal. It stores the observation count and one of `unavailable`, `immature`,
or `mature` baseline states for each signal. A missing target-day value remains
`unavailable`; it is never filled from the baseline.

- HRV stores rolling-median baseline, `current / baseline`, and ratio minus 1.
- Resting HR stores rolling-median baseline and `current - baseline` bpm.
- Sleep duration stores rolling-median baseline, `current - baseline` minutes,
  and non-negative debt `max(baseline - current, 0)`.

The row stores formula version, window, minimum history, source observation
revision, and timestamp state. `source_staleness` is metadata only:
`current_local_date`, `stale` (observation timestamp before the local date),
`late` (after it), or `unknown` when no observation timestamp exists. It never
changes a value's eligibility or silently carries an earlier value forward.

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

## Telegram collection

The existing one-tap next-day recovery check remains unchanged. After its
successful write, Telegram offers an optional physiology block; skipping it
does not block recovery feedback, readiness, or a recommendation.

The block collects sleep duration, optional sleep quality, HRV, and resting
heart rate as separate short numeric messages. Each step has a skip action;
skipping keeps any existing value untouched, so a partial submission is valid.
Starting the block again on the same local date shows the stored values before
editing and writes through the same service with `source = telegram`.

Telegram session rows contain only UI state and a rotating callback token, not
physiology values. A replaced, completed, or previous-date token is rejected
as stale. Accepted values are saved immediately through the normal versioned
observation contract. This flow does not calculate baselines or recompute
readiness.
