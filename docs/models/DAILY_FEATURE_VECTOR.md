# Daily feature vector

## Status

`daily_feature_vector_v1` is an implemented, read-only research-input contract.
It does not calculate readiness or select a model. A successful daily delivery
now persists this vector as an immutable `research_feature_snapshot`; temporal
partitioning and export remain a separate offline concern of #133.

## Contract

The builder requires `user_id`, a configured local calendar date, and a
timezone-aware `cutoff_at`. It returns a versioned JSON object with explicit
feature names under `features`, an availability state and reason codes for every
feature, source metadata, and the list of eligible recent response activities.

The current names cover load/freshness, recent response, morning feeling,
manual physiology, and preserved historical physiology. A missing value is
always `null` with `availability: unavailable`; it is never replaced by zero or
a neutral score.

## Temporal boundary

The cutoff means information known by Whatte, not merely an event's reported
date. Activities require their start, raw fetch, and response computation to
precede the cutoff. Feedback requires both creation and current update to
precede it. Manual physiology requires both the current source update and
derived-feature computation to precede it. Derived load and historical
physiology require their persisted update timestamp to precede it.

Current mutable rows that were updated after the cutoff are deliberately marked
unavailable: this avoids post-cutoff leakage but does not claim to reconstruct a
superseded historical state. Immutable decision-time state continues to belong
to #78.

Activity dates are resolved with the supplied timezone, not UTC date casts.
The recent response window is seven local calendar days ending at the requested
date; all eligible activities are retained and the most recent is exposed by
the fixed `training_response.latest.*` feature names.

## Use

Run from `backend/` with the normal read-only database configuration:

```bash
python -m scripts.build_daily_feature_vector \
  --user-id USER --local-date 2026-10-01 \
  --cutoff-at 2026-10-01T08:00:00+03:00 --timezone Europe/Moscow
```

The command uses a repeatable-read, read-only transaction and writes only JSON
to stdout. Do not commit personal output.
