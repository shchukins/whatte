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
- No additional sleep, stress, motivation, or fatigue questionnaire without a
  documented persistence and calibration use.

## Related contracts

- [Readiness API](../api/READINESS_API.md)
- [Dated user profile](../product/USER_PROFILE.md)
- [Subjective feedback](../models/SUBJECTIVE_FEEDBACK.md)
