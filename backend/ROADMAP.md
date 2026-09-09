# Backend Roadmap

## Already implemented

- Strava ingestion baseline
- preserved historical HealthKit raw and normalized tables
- `health_recovery_daily`
- baseline-aware recovery scoring
- `recovery_explanation_json`
- `load_state_daily_v2`
- `readiness_daily`
- `good_day_probability` baseline
- wearable-independent daily readiness pipeline
- Web Today feedback and dated profile management
- Telegram daily readiness, post-ride RPE, and next-day recovery flows
- deterministic recommendation and shared briefing contract for API, Web Today,
  and Telegram delivery
- pilot-report and decision-context snapshot storage for calibration evidence

## Next steps

- complete and review the 14-day morning-loop pilot before changing model
  weights or thresholds
- readiness / probability calibration from stored evidence; the current
  `good_day_probability` remains `readiness_score / 100`, not a calibrated
  probability
- resolve the remaining notification-formatting drift so delivery code consumes
  only the canonical decision contract
- define a bounded first non-cycling Strava load slice; unsupported activities
  must remain explicit rather than estimated
- expand derived features only when a concrete deterministic consumer exists
- evaluate personalization or prediction only after calibration criteria and
  validation data are agreed
