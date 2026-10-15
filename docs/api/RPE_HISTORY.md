# Personal RPE history v1 (#194)

Implemented read-only context after an independent selection; never predicts,
prefills, rescales or saves RPE. Existing write and effective source priority
(Strava → Telegram → Web) remain authoritative.

## Service and Web contract

`get_rpe_history(user_id, activity_id)` returns `version=rpe_history_v1`,
`status=available|insufficient_data`, `target_metrics`, `matches`, `count`,
`median`, `range`, `reason_codes`. Insufficient evidence returns empty matches,
zero count and null statistics. Each match carries ID, owner, sport, timestamp,
duration seconds, NP watts, IF, TSS, VI, effective RPE, original source/scale,
quality, reasons, limitations and historical FTP implied by stored NP/IF.

`GET /today/rpe-context/{activity_id}?score=1..10` renders Today with selected
draft and history before saving. `fragment=true` renders an escaped HTML fragment.
Missing/invalid score is 422; unowned/deleted/excluded/duplicate target is 404.
Read failure is 503 for fragments; native preview preserves draft and shows an
error. Responses use `Cache-Control: no-store`. This internal SSR endpoint shares
Today edge authentication and configured-athlete boundary; it accepts no user ID.
It does not replace the write API or its CSRF checks.

Initial Today neither queries nor embeds historical ratings. Radio change triggers
an abortable read; hover/focus previews and stored Web values do not trigger it.
No automatic POST or retry. Native comparison submits GET after required selection;
saving remains explicit. Failed history reads leave selection/save usable.
Historical sessions open in Strava.

## Deterministic policy

Read at most 200 most recent rated canonical workouts in the preceding 365 days,
strictly before target start and no later than now. Every join enforces the same
owner. Join effective resolution to its matching original source/score observation;
only integer `rpe_1_10` values 1–10 qualify. Legacy 1–5 values are excluded, never
multiplied. Require exact activity type: Ride and VirtualRide remain separate;
other sports return insufficient evidence in v1.

Require finite positive normalized duration, NP, IF, VI in both sessions. Missing
power returns neutral insufficient evidence. Gates relative to target:

- Duration difference ≤25%; NP difference ≤20%.
- Absolute IF difference ≤0.12; absolute VI difference ≤0.10.
- Historical FTP (`stored NP / stored IF`) difference ≤15%. Current profile FTP
  is never substituted; recalculation of stored metrics can change comparison.

Quality = `1 - (0.4 * duration_difference/0.25 + 0.4 * IF_difference/0.12 +
0.2 * VI_difference/0.10)`, requiring ≥0.65. These conservative policy thresholds
are similarity heuristics, not physiological equivalence or validated probability.
NP/FTP are gates, not extra votes. TSS is display-only: it already depends on
duration/IF, so scoring it again would double count. Duration uses normalized
moving time with normalized duration fallback.

Sort quality descending (six decimals), then start descending, then ID descending.
Keep at most five; require at least three before exposing any ratings/statistics.
Median and observed min/max describe only those matches.

The reused metrics contract has no reliable versioned interval structure. VI is
coarse variability, never evidence of matching intervals. All matches declare
`match_quality=reduced` and `interval_structure_unavailable`; UI displays this
limitation. Equal aggregates can conceal different intervals, fatigue or conditions.
History is subjective context, never a correct answer. No migrations, stream scans,
ML, readiness changes or external API calls are introduced.
