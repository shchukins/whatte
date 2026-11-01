# Web Today surface

> Scope note, 2026-10-21: this document specifies the **implemented readiness
> baseline**, unchanged by the new [product direction](../ai/PRODUCT_CONTEXT.md).
> Since 2026-10-31 Today also consumes the existing [training time policy](../models/TRAINING_DECISION_POLICY.md)
> and [persisted context](../data/TRAINING_CONTEXT.md), as a separate proposal contract.
> A high readiness category does not establish which workout best serves a block.

## Purpose

`/today` is the protected, responsive FastAPI/Jinja2 surface for the
single-user daily loop. It renders backend-owned state; it does not calculate
readiness, recommendation, or missing-data fallbacks in the browser.

Its visual language follows [Whatte visual identity](VISUAL_IDENTITY.md):
the daily reading is presented as an editorial issue, with the stored
decision first, supporting signals and feedback next, and a compact 7-day overview linking to the 14-day diary.

## Training proposal, 2026-10-31

The first block shows today's saved session (type, minutes, key/supporting),
block priority and a native time editor. Known capacity is prefilled. Unknown
capacity, absent goal/plan and multiple same-day sessions remain explicit.
Training permission is a separate explicit input. A disclosure collects intensity
permission, future compatibility reviews and permitted existing-plan substitutes.

The shared backend policy owns KEEP/SHORTEN/SUBSTITUTE/RESCHEDULE/SKIP, reasons,
stimulus tradeoffs, week consequences and alternatives. Insufficient context
produces uncertainty. Unknown load is visible without opening a disclosure;
activities, RPE, missing optional physiology and data limitations remain available.

When today's plan and block priority exist, this is the primary workout answer.
The unchanged readiness surface is collapsed as supporting state; its historical
category/briefing remains available and is explicitly distinguished from workout
choice. Without that plan context the readiness baseline remains visible with a
clear fallback label. Failures of the plan read are displayed, never empty history.

Only available time is persisted. Preview constraints live in a local-date-scoped
URL and are cleared for another day. Viewing/reloading never accepts proposals,
changes the plan, creates assignments or records decision history. Confirmation
and plan/activity linkage remain Task 4.

## Existing readiness behavior

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
  The reusable editorial selector (#192) uses ten increasing SVG bars in one
  horizontal row, backed by native required radios (integer 1–10). Full columns
  are click/touch targets; selection and keyboard focus have distinct ink outlines.
  Arrow keys select within the group. A numeric preview and selected annotation
  update before the separate «Сохранить RPE» confirmation; choosing never writes.
  There is no initial choice unless a Web observation or failed-save draft exists.
  The Web selection (including no selection) is shown separately from the
  effective RPE, which identifies Strava, Telegram fallback, or Web
  fallback. If observations disagree, the page shows each recorded source
  score and the Strava > Telegram > Web resolution rule.
  When effective RPE is available, the page says additional input is unnecessary
  and keeps the voluntary Web editor in closed native details, including
  Strava-only and Telegram-only observations. Without effective RPE the editor
  opens immediately, even if a Web observation exists without resolution.
  Saved Web selections remain available for editing. Failed native saves retain
  the submitted draft and reopen the editor, with a linked error. Before input, the editor
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
Saved RPE and morning feeling appear as small colored circles with one number,
using the exact discrete colors of their respective Today input scales. Feeling
keeps its text label and RPE keeps its source; separate conflicting RPE observations
use the same circles. Accessible labels include the full scale (RPE out of 10,
feeling out of 5). The workout row uses the short label «RPE» with muted text
and a smaller circle than morning feeling. Missing scores remain «Нет оценки» without a colored circle.
The compact workout summary (#177) covers the target local date and previous
six dates, with explicit ISO endpoints. It aggregates the existing unfiltered
canonical activity read: recorded workout count, known duration (including zero),
missing-duration count and persisted effective RPE coverage. Missing durations
are explicitly disclosed beside the known sum; failed activity reads make the
summary unavailable, never zero. Readiness failures do not hide workout totals.
The summary is unchanged by the visual RPE filter and links to it with the
distinct label «Без RPE за 14 дней». It adds no database reads or writes.
The same seven-date summary shows «Учтено в модели нагрузки: N из M тренировок»:
M is the unfiltered recorded canonical workout count, N is confirmed inclusion
under the current stored load assessment, not historical readiness inclusion or
a percentage of physical load. Classification shares the pilot coverage contract
and `resolve_activity_load`; it does not infer inclusion from RPE, duration or
positive TSS. Zero power metrics retain the resolver's inclusion semantics.
An absent `activity_metrics` v1 row (`unavailable_metrics_record`) is unknown,
not an exclusion. Unknown counts are shown separately; an entirely unknown
nonempty window displays unavailable coverage rather than zero. An empty window
has 0 of 0; a failed activity read makes the whole summary unavailable.
Known exclusions have one primary reason each, displayed with Russian labels:
`unsupported_sport` («Вид спорта пока не поддерживается») takes precedence over
`missing_required_power_metrics` («Нет необходимых данных мощности»), avoiding
double counting. The query adds only the presence of the already joined metrics
row, and the template renders backend counts and labels without domain rules.
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

## RPE selector form contract (#192)

`POST /today/rpe/{activity_id}` accepts exactly one URL-encoded `score` field,
integer 1–10, within 128 bytes. Invalid/missing/duplicate fields return a rendered
422; unowned or ineligible activities return 404. Cross-site forms are rejected.
It delegates to the existing `/today/rpe/{activity_id}/{score}` write contract,
which remains supported. Success redirects with 303 to the selected activity and
validated `return_day`; save failure returns 503 with the attempted score retained.
Source precedence and backend recomputation are unchanged.

The presentation macro `today/rpe_selector.html` receives a stable instance ID,
controlled Web/draft value and the existing RPE options; it owns no persistence.
It composes shared paper, grid, watercolor, ink and annotation primitives. Native
radios, details, CSS numeric preview and confirmation work without JavaScript.
The optional script announces changes. With fetch, the existing lifecycle locks
radios and buttons during POST, confirms the returned stored Web value, and
requires an explicit check or retry after an uncertain result. BFCache restores
the controls without resubmitting. Recovery keeps its one-tap submission behavior.


## Contextual session-RPE guidance (#193)

Implemented in the shared selector on Today and Diary. Every integer has a
Russian description, breathing/speech cue, illustrative endurance example and
comparison with adjacent values in `today/rpe_guidance.html`. Existing localized
labels and the `rpe_1_10` integer contract are retained, including 6 «Ровная
нагрузка». Its explanation clarifies that steady work can feel somewhat hard.
This is Whatte's existing 1–10 session effort scale with editorial guidance,
not a verbatim reproduction of Borg CR10/Foster anchors, a new scale, a
conversion of historical 1–5 feedback, or a prescription of intensity.
Missing stays unselected. Historical data and effective-source precedence do not
change; no load, recovery or readiness formulas change.

The question is how hard the **whole session** felt, including easier portions;
it is not a peak-interval score, a mathematical average of interval scores, or
the duration-weighted training-load metric sometimes also called session-RPE.
The selector always states «Оцени всю тренировку, а не только её самый тяжёлый
момент». Duration, fatigue and conditions can change the perception of any
example. No exact RPE is derived from power, HR, IF, zones or session type.
Breathing/speech cues describe moments only and cannot identify an exact
whole-session score.

Semantic references checked on 2026-10-15:

- [Primary session-RPE study](https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2020.00919/full)
  for overall session perception rather than one moment; the UI adds no timing
  restriction or new measurement protocol.
- [CDC relative intensity and talk test](https://www.cdc.gov/physical-activity-basics/measuring/)
  for qualitative breathing/speech cues only. Its instantaneous intensity scale
  and numeric cutoffs are not mapped onto the product's session scores.

CSS exposes one inline guidance panel: checked value by default, pointer preview
on devices with fine hover, then keyboard-visible focus with highest priority.
Leaving hover restores the selected panel without changing the radio value.
Touch selection and native keyboard arrows expose the same content. Every radio
links to its own description with `aria-describedby`; instance IDs are unique.
The numeric selected readout remains separate from the preview. These behaviors
work without JavaScript; optional JS still announces only selection changes.
Parent forms retain explicit confirmation, draft/error retention, loading locks,
CSRF/user validation and no automatic POST retries.

Validation on 2026-10-15: Chromium at 1440px previewed all ten values without
selecting, restored selected 7 after previewing 8, and exposed all ten descriptions
with native keyboard arrows. A second selector retained its own value. At 390px,
a touch context with JavaScript disabled selected all ten and showed the matching
panel; no horizontal overflow. Desktop/mobile screenshots were inspected.
Reduced-motion mode added no animation. Local selector contract tests cover all
ten descriptions, per-radio accessible links and instance ID uniqueness; existing
Today/Diary tests cover draft/save/error behavior.


## Training choice loop (2026-11-01)

Today adds native accept/decline and explicit activity-to-assignment confirmation
using the [backend loop contract](../data/TRAINING_CONTEXT.md#decision-loop-2026-11-01).
GET stays read-only; accepted/declined state survives reload. Recorded work today
is shown ahead of a new training prescription even without a plan link or metrics.
Fulfilled/different and pending/complete remain distinct. This is a bounded functional
addition to the existing screen, not implementation of the #197 visual prototype.
