# Dated user profile

Implemented in the backend and Web Today at `/today/profile`.

The existing edge protection for `/today*` applies. The account is resolved from
`DAILY_READINESS_USER_ID`; this is a single-user surface, not an account system.

## Behavior

- FTP (watts), HR max (bpm) and weight (kg) have independent effective-date histories.
- Each value applies from its date until the next entry for the same metric.
- Saving the same metric/date corrects that entry; it does not append a duplicate.
- Future dates, non-finite values, FTP outside 1–1000 W and weight outside
  1–500 kg, and HR max outside whole numbers 1–250 bpm are rejected. Limits are input validation,
  not physiology thresholds.
- Historical FTP and HR max rows are copied from `user_training_profile`
  without overwriting manual corrections. No HR max is inferred from age.
  Missing values remain unavailable.
- Weight starts empty. Historical HealthKit weight remains separate; a manually
  entered profile weight is not a recovery observation and does not affect TSS
  or readiness.

## Calculations

Both ingestion and the debug metric endpoint resolve FTP and HR max on the
activity's calendar date in `WHATTE_TIMEZONE`, independently for each metric, falling back
to the dated legacy profile only when no manual entry exists by that date.
Future entries never apply to earlier activities. The resolved values are
preserved in `activity_metrics.raw_json.ftp_watts` and `.hr_max`. HR max is
provenance only in the current metrics; it does not affect TSS or readiness.
The TSS formula remains unchanged.

Legacy power/HR zone boundaries use their own dated training profile. Editing
FTP or HR max does not silently rescale these boundaries. If zone boundaries
are absent,
zone times are unavailable (`null`). Zone editing is outside this first version.

Changing FTP or HR max persists `needs_recompute`; an unchanged same-date save
does not schedule new work. HR max changes refresh activity provenance through
the same stored-data pipeline without changing formulas or zone boundaries.
The page offers an explicit recalculation
from the earliest pending date. It rebuilds stored activity metrics, canonical
activity responses in chronological order, daily load, fitness and readiness
through today, including rest days. No Strava requests or Telegram messages are
sent. Existing notifications and decision snapshots are not rewritten.

Recalculation is synchronous. Per-user advisory locks serialize profile edits
and recalculations; another simultaneous submission receives HTTP 409. Existing
pipeline services commit in stages. A failure can therefore leave partially
updated derived data: pending flags are cleared only after all stages succeed,
and the page explicitly offers a retry. Missing stored streams must be restored
before a failed calculation can succeed. Ingestion is not locked by this form;
if it runs concurrently, repeat the calculation after ingestion completes.

## Deployment

Apply `db-init/011_user_profile.sql` and then `db-init/020_user_profile_hr_max.sql`
to the existing database before starting the updated backend and worker. Merely restarting Docker does not apply db-init SQL
to an existing volume. The migration is additive and rerunnable; it preserves
existing profile entries. Deploy the same code to both backend and worker.

Migration 020 extends validation and backfills valid legacy HR max rows without
overwriting existing entries or scheduling recalculation for the backfill.
Verify current values, independent date histories and pending status. Production
migrations and user data corrections are not applied by a code deployment alone.

## Navigation and language

Profile shares the «Сегодня · Профиль» navigation with Today. The active page
is underlined and marked with `aria-current="page"`; links support keyboard focus
and have a minimum height of 44px. Both pages use Russian UI labels and `lang="ru"`.
The dated values, save and recompute behavior remain unchanged.


## Editing in Web Today

Each current metric has an «Изменить» link to the existing form, selecting that
metric and its current value. The initial effective date is local today in
`WHATTE_TIMEZONE`, independently of the stored entry date. Links and native
POST forms work without JavaScript; JavaScript additionally focuses the value
and updates the current value and explanation when the metric selector changes.
Without JavaScript, all three consequences remain visible before saving.

The form supports backdating and explicitly explains replacement of a matching
metric/date. FTP requires separate recalculation of affected metrics and daily
states; HR max refreshes provenance; weight requires no recalculation. Saving
reports the metric and effective date and does not claim recalculation succeeded.
Validation failures retain the raw metric, value and date, link an alert summary
to the invalid fields, and use `aria-invalid`/`aria-describedby` for inline errors.
Save failures retain the form for retry. A recalculation failure or lock conflict
keeps the pending section and separate retry button visible.
