# Training Response Metrics

## 1. Purpose

`activity_response_metrics` is the deterministic activity-level layer that
describes how much a completed workout cost the athlete. It combines existing
objective activity metrics with optional post-ride RPE without requiring
HealthKit.

The layer is versioned, persisted, recomputable from source data, and separate
from readiness scoring.

## 2. Inputs

- canonical, non-deleted, non-excluded `strava_activity_raw` row
- `activity_metrics` version `v1`
- `time`, `watts`, and `heartrate` raw streams when present
- resolved 1-10 RPE from `activity_rpe_resolution` when present

Missing inputs remain unavailable. They are never converted to zero.

## 3. Metrics and version boundary

Historical version `v1` used 1-5 Whatte feedback. Current version
`v2_rpe_1_10` uses only 1-10 source observations. The objective formulas
are unchanged; the RPE cost metrics use the new scale. No old 1-5 feedback is
converted or included in the new version's comparable baseline.

The response rows persist:

- average and normalized power
- average heart rate
- average-power / HR and normalized-power / HR ratios
- aerobic decoupling for eligible steady workouts
- effective RPE on the version's declared scale
- session-RPE load: `duration_minutes * RPE`
- RPE / intensity factor
- session-RPE load / TSS
- per-metric availability and reason codes

### 3.1 Aerobic decoupling

An activity is eligible only when:

- duration is at least 30 minutes
- variability index is available and `<= 1.10`
- aligned positive power and HR cover at least 80% of stream duration

For eligible activities, time-weighted power / HR is calculated independently
for the first and second halves:

```text
decoupling_pct = (first_half_power_hr / second_half_power_hr - 1) * 100
```

A positive value means power / HR deteriorated in the second half. Pauses,
missing samples, non-positive power, and non-positive HR do not contribute.

### 3.2 Intensity bands

Comparable groups use activity type plus the following intensity-factor band:

- `< 0.55`: `recovery`
- `0.55 .. < 0.75`: `endurance`
- `0.75 .. < 0.90`: `tempo`
- `0.90 .. < 1.05`: `threshold`
- `>= 1.05`: `high_intensity`

Without intensity factor, the response row remains valid but no intensity-band
baseline is claimed.

## 4. Personal baseline

Each response row stores a baseline snapshot from up to 20 earlier canonical
activities with the same user, activity type, intensity band, and response
version. The current activity is excluded.

For every metric independently:

- at least 3 non-null historical values are required
- the baseline is their median
- deviation is `(current / baseline - 1) * 100`

The snapshot stores sample counts and explicit insufficient-sample reasons. No
synthetic aggregate `response_score` is created in either version.

## 5. Lifecycle

The row is upserted:

- after activity metrics and canonical deduplication in the Strava pipeline
- after effective 1-10 RPE changes through Strava, Telegram, or Web Today

Only a change of effective score recomputes response rows and their affected
seven-day readiness windows. A score change also refreshes up to 20 later
comparable baseline snapshots. Equal Strava and Telegram observations retain
both sources without repeating the calculation.

## 6. Readiness boundary

The latest response row from the preceding seven days is exposed in the stable
`response` signal family:

During the version transition, a historical `v1` row can still describe an
older activity when no current-version row exists for it. For an activity with
both versions, `v2_rpe_1_10` wins. Each row's baseline remains within its
own version; the two RPE scales are never compared.

- `availability = available`
- baseline-backed normalized power / HR, aerobic decoupling, and one normalized
  RPE-cost metric can produce a readiness-bearing score
- raw RPE, absolute session-RPE load, TSS, duration, power, and HR are never
  scored directly
- insufficient baseline remains explicit context with `used = false`,
  `score = null`, and reason `response_baseline_insufficient`
- scoring weight fades after the first day and reaches zero on day seven

Readiness model `v2_signal_composition_response_v1` owns the aggregate response
score and weighting. Current activity response rows use `v2_rpe_1_10`; no synthetic
aggregate is persisted back into `activity_response_metrics`.

### 6.1 Component normalization

```text
efficiency_score = clamp(50 + 2 * normalized_power_to_hr_deviation_pct, 0, 100)
subjective_cost_score = clamp(50 - 2 * selected_rpe_cost_deviation_pct, 0, 100)
drift_score = clamp(50 - 10 * (current_drift - baseline_drift), 0, 100)
```

`session_rpe_load_per_tss` is preferred for subjective cost;
`rpe_per_intensity_factor` is its fallback. They are never counted together.
The two objective components are averaged first, then the available objective
and subjective channels are averaged. Baseline equality is neutral at `50`.

Drift uses a percentage-point difference rather than relative percentage
deviation because its baseline may legitimately be zero or negative.
