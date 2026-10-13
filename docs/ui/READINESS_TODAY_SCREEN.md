# Web Today surface

## Purpose

`/today` is the protected, responsive FastAPI/Jinja2 surface for the
single-user daily loop. It renders backend-owned state; it does not calculate
readiness, recommendation, or missing-data fallbacks in the browser.

Its visual language follows [Whatte visual identity](VISUAL_IDENTITY.md):
the daily reading is presented as an editorial issue, with the stored
decision first, supporting signals and feedback next, and a compact 7-day overview linking to the 14-day diary.

## Current behavior

- Presents one main answer for the stored result date: backend recommendation,
  shared briefing, and readiness labeled N/100. `good_day_probability` remains
  in the API but is not displayed on Today. Status text uses neutral styling.
- Shows calculation and source timestamps in `WHATTE_TIMEZONE`. A stale result
  or a result from another date has an always-visible warning and its actual
  date; a historical briefing is explicitly labeled with that date. Freshness
  policy and shared briefing text remain unchanged.
- Places existing signal availability/participation and source timestamps in
  the keyboard-accessible «Почему такая рекомендация» disclosure under the
  answer, followed by morning feedback. Missing/error states have no invented
  score or recommendation. RPE, observations and the history overview remain available.
- Shows optional historical physiology only when it belongs to the same date;
  unavailable physiology is not an error and is not rendered as a fake score.
- Lets the user create or edit today's one-tap next-day recovery score.
  The 1–5 scale stays in one row, with Russian labels wrapping at 320 px.
  The backend recomputes readiness for that date after the idempotent upsert.
- Lets the user create or edit RPE for the latest eligible canonical activity.
  The form uses numeric 1–10 buttons in two rows (1–5, then 6–10) at widths
  up to 900 px and a single row on wider screens. Each button has its own
  semantic anchor and accessible name; all ten controls are visible without
  horizontal scrolling, with keyboard focus in numeric order. Selection is
  marked by a border and `aria-pressed` reflects only the Web observation.
  The Web selection (including no selection) is shown separately from the
  effective RPE, which identifies Strava, Telegram fallback, or Web
  fallback. If observations disagree, the page shows each recorded source
  score and the Strava > Telegram > Web resolution rule.
  When effective RPE is available, the page says additional input is unnecessary
  and keeps the voluntary Web editor in closed native details, including
  Strava-only and Telegram-only observations. Without effective RPE the editor
  opens immediately, even if a Web observation exists without resolution.
  Saved Web selections remain available for editing. Before input, the editor
  explains that Web is stored separately and cannot override available Strava
  or Telegram observations. Native forms and details work without JavaScript.
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

Today and Profile check `GET /today/context` on `pageshow` and return to a
visible tab. The protected, read-only endpoint returns the current server date
in `WHATTE_TIMEZONE` with `Cache-Control: no-store`, without database reads.
A changed day shows an explicit GET refresh link; pages never reload
automatically, so edited Profile/observation fields remain in the DOM. The
device date is not used. Recovery and observation POST date guards still apply.

BFCache restoration resets only locally introduced button/busy states and
Profile submit labels. It preserves input and explains that a pending send's
result must be checked. Visibility alone does not unlock a pending POST.
Late callbacks from a restored feedback request cannot navigate or claim a
result. No lifecycle event retries a POST, and no personal values are stored
outside the DOM. Native forms remain available without JavaScript; refresh
links use GET even when the current document came from a recompute POST.

Issue #176 validation: Chrome against local fixture-backed routes, with real
BFCache enabled, passed Profile save→Back and recompute→Back (restored labels,
enabled buttons and retained input). Tab switching retained input. Mocked server
midnight retained edited Profile and observation fields with a refresh notice.
A held/lost feedback response plus a simulated persisted `pageshow` restored
controls without another POST or a late callback navigation. Lost-response
handling and 320px layout passed. With JavaScript disabled, Profile save,
recompute and recovery save followed native POST flows. Existing backend stale
date tests and the read-only/no-store context test passed; no browser framework
was added.

Recovery forms carry the rendered `local_date` (ISO YYYY-MM-DD). Both native
POST and fetch send URL-encoded fields. Before writing, the server compares
that date with the current date in `WHATTE_TIMEZONE`; a stale date returns 409,
and missing/invalid/duplicate dates return 422. Parsing accepts only one date
field and at most 128 body bytes. Refusals show an accessible message and a
reload Today link, without a success redirect or saving on another day.
The configured user, recovery score and backend recomputation remain unchanged.

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

## Russian presentation and navigation

Today, Diary and Profile share keyboard-accessible «Сегодня · Дневник · Профиль» navigation,
with `aria-current="page"`, an underlined active link and 44px minimum link height.
All three pages declare `lang="ru"`. Forms, scales, units, saved messages, validation
errors and empty states use Russian labels; FTP, HRV, RPE and source names remain.
Web-only labels map existing backend codes without score thresholds. Unknown
codes have a neutral label. The main briefing remains the shared formatter output;
raw recommendation reasons and section errors are available as technical details.
POST routes, values, source priority and calculation behavior are unchanged.

## Diary

`/today/history` uses the same Caddy `/today*` protection and configured user
as Today/Profile. It presents all 14 local dates, including missing days, with
a small dated readiness figure and exact readiness, morning feeling and
backend recommendation in the daily list. Unsupported model versions are
separate, have no plot and do not receive newly derived recommendations.
The caption explicitly describes current saved values that can change after
recomputation, rather than immutable morning decisions or delivered messages.

Each day includes every recorded eligible canonical workout, local start time,
nullable duration and persisted effective RPE/source. Source conflicts show
the separate observations. No recorded workouts means only absence of records.
Activity and readiness/recovery failures have independent states.
The compact workout summary (#177) covers the target local date and previous
six dates, with explicit ISO endpoints. It aggregates the existing unfiltered
canonical activity read: recorded workout count, known duration (including zero),
missing-duration count and persisted effective RPE coverage. Missing durations
are explicitly disclosed beside the known sum; failed activity reads make the
summary unavailable, never zero. Readiness failures do not hide workout totals.
The summary is unchanged by the visual RPE filter and links to it with the
distinct label «Без RPE за 14 дней». It adds no database reads or writes.
At narrow widths the list becomes a vertical feed; desktop uses compact
columns. Exact data never depends on hover or JavaScript.

Diary workout links «Все» (`/today/history?rpe=all`, also the default) and
«Без RPE» (`/today/history?rpe=missing`) work without JavaScript. Only workouts
with persisted effective `rpe_score is None` appear in the latter; scored
Strava, Telegram and Web observations, including conflicts with an effective
score, are excluded. The count uses the same 14-day read. Calendar days and
the readiness figure remain complete. Days without matches say «Нет тренировок
без RPE»; failed activity reads say «Не удалось загрузить тренировки» and the
count is unavailable. Unknown filter values return HTTP 422 before reading.

«Оценить/изменить RPE» links to `/today?activity_id=…&return_day=YYYY-MM-DD#rpe`; writes still use
Today's existing eligibility/user checks. There is no historical recovery editor.
Today retains a 7-day figure and exact scores plus «Открыть дневник».

Historical RPE navigation (#174): Diary links carry `activity_id` and the ISO
`return_day`. Today titles an explicitly selected workout with its local date;
the readiness above remains today's readiness. Native RPE forms, successful
POST→303→GET and save-error pages preserve the selected activity and validated
day. «Вернуться к дню в дневнике» points only to `/today/history#day-YYYY-MM-DD`.
Return context is accepted only for the owned activity's local date inside the
current 14-day diary window; malformed, mismatched and out-of-window context
is discarded. No URL or arbitrary anchor is accepted. Diary day anchors are
stable, and both readiness figures use keyboard-accessible day links, including
missing days, with exact dated values in accessible labels.
