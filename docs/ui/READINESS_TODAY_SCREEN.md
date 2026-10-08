# Web Today surface

## Purpose

`/today` is the protected, responsive FastAPI/Jinja2 surface for the
single-user daily loop. It renders backend-owned state; it does not calculate
readiness, recommendation, or missing-data fallbacks in the browser.

Its visual language follows [Whatte visual identity](VISUAL_IDENTITY.md):
the daily reading is presented as an editorial issue, with the stored
decision first, supporting signals and feedback next, and 14-day history as
an annotated figure and exact-value table.

## Current behavior

- Shows the latest current-version materialized readiness, its deterministic
  recommendation, reason, briefing, signal availability, source-data freshness,
  and a 14-day calendar history. Good-day probability is shown only when the
  stored backend field is available; otherwise the stored readiness score is
  labeled as such. Neither value is recalculated by the browser.
- Shows optional historical physiology only when it belongs to the same date;
  unavailable physiology is not an error and is not rendered as a fake score.
- Lets the user create or edit today's one-tap next-day recovery score.
  The backend recomputes readiness for that date after the idempotent upsert.
- Lets the user create or edit RPE for the latest eligible canonical activity.
  The form uses a single horizontal 1-10 scale with numeric buttons, semantic
  anchors, keyboard focus, and horizontal scrolling at narrow widths. The
  displayed effective RPE identifies Strava, Telegram fallback, or Web
  fallback. If observations disagree, the page shows each recorded source
  score and the Strava > Telegram > Web resolution rule.
  A changed effective score updates the response path through backend
  services; raw RPE is not a direct readiness score.
- Provides dated FTP/weight profile history and an explicit stored-data-only
  recomputation action. It is not a multi-user account API.

## Optional manual physiology

After recovery and RPE, Today shows optional sleep duration (minutes), sleep
quality (1–5, very poor to very good), HRV (ms), and resting heart rate (bpm)
for the current local date. Each missing field is unavailable, including an
all-null record. Values entered through Telegram and Web share one record;
source and update time are displayed separately from readiness signal evidence.

A collapsed editor supports partial entry and later editing. Empty fields are
omitted and preserve existing values; an explicit Clear checkbox sends null.
Numeric validation and revisions use the shared manual physiology model/service.
The form preserves entered values and clear actions on validation/write errors;
a failed read only disables the optional collection block. A form from a previous
local day is rejected with a request to reload Today. Blank submissions do not
create observations. Identical repeats do not create revisions.

`POST /today/physiology` uses the existing edge-authenticated form boundary and
POST/redirect/GET flow. It does not expose the dedicated API token or select a
browser-supplied user. Saving raw observations does not recompute readiness or
personal baselines. There are no physiology history charts or frontend scores.

## Ownership and safety

- `DAILY_READINESS_USER_ID` selects the account; browsers cannot select an
  arbitrary user.
- Caddy protects `/today*`; the technical API domain does not expose these
  routes.
- Forms use POST/redirect/GET, validate scores on the backend, and reject
  cross-site submissions.
- A failed write never claims local success. Missing, partial, or stale
  readiness is shown using the backend contract.

## Deliberate limits

- No SPA, frontend build step, OAuth account system, or client-side model logic.
- No workout construction, duration prescription, calendar-aware planning, or
  HRV or 28-day load figure without a real backend data contract. The 14-day
  readiness figure uses the existing history rows and marks missing dates.
- No additional stress, motivation, or fatigue questionnaire without a
  documented persistence and calibration use.

## Related contracts

- [Readiness API](../api/READINESS_API.md)
- [Dated user profile](../product/USER_PROFILE.md)
- [Subjective feedback](../models/SUBJECTIVE_FEEDBACK.md)

- [Manual physiology](../data/MANUAL_PHYSIOLOGY.md)
