# Personal Physiology Features

## Purpose

`personal_physiology_features_v1` converts optional manually entered sleep,
HRV, and resting-HR observations into transparent, personal-relative features.
It supports research and the future daily feature vector. It is not a recovery
score and does not change production readiness.

## Inputs and temporal boundary

The only source is `manual_physiology_observation`. Historical HealthKit rows
are intentionally excluded. For target local date `D`, each per-signal
baseline uses non-null observations in the inclusive calendar window
`[D - 28 days, D - 1 day]`. The observation on `D` is never in its own
baseline; later rows are not queried.

At least seven earlier observations are required for a mature baseline. The
median is used so a single valid but unusual observation cannot dominate the
reference. Missing calendar days do not create synthetic observations.

## Derived values

For median baseline `B` and target value `X`:

```text
HRV ratio       = X / B
HRV deviation   = X / B - 1
RHR delta       = X - B bpm
sleep deviation = X - B minutes
sleep debt      = max(B - X, 0) minutes
```

No derived value is emitted for an unavailable target value or immature
baseline. The row retains its availability, historical observation count, and
baseline state rather than substituting zero or a neutral value.

## Version and reproducibility

Each persisted row records `feature_version`, window length, required history,
source observation revision, and the input timestamp state. A deterministic
command recomputes one user/date from stored manual observations:

```text
python backend/scripts/recompute_personal_physiology_features.py \
  --user-id sergey --local-date 2026-10-01
```

This command has no readiness, notification, or HealthKit side effect.
