# Personal Effort Baseline & Deviation v1 (#195)

Implemented as a read-only descriptive service, separate from readiness,
activity response metrics and all write/recomputation/notification paths.
`PED = actual_RPE - expected_RPE`. A positive value describes a higher rating
than the personal comparable-session median; it does not establish fatigue,
inadequate recovery or a cause. Expected RPE is a descriptive reference, not a
validated prediction or the correct rating.

## Method

`personal_effort_deviation_v1` reuses the exact sport/power/duration/FTP/VI gates,
quality score and deterministic tie-breaking of [RPE history v1](../api/RPE_HISTORY.md).
Ride and VirtualRide remain separate. No power or incompatible scale yields
unavailable evidence. Only original `rpe_1_10` integer scores 1–10 from the
current effective Strava → Telegram → Web resolution qualify; legacy 1–5 is
never rescaled, and no lower-priority observation substitutes for a late edit.

Window: preceding 365 days, inclusive lower bound, strictly before target start.
After temporal/availability filtering, read at most the latest 200 candidates,
rank with the shared matcher and keep at most five. Require three matches.
Three is a minimum descriptive sample policy inherited from #194, not a
statistical power or calibration guarantee. All usable results have reliability
`limited`; there is no unvalidated high-confidence tier.

Expected RPE is the unweighted median. Median absolute deviation (MAD, unscaled)
and observed min/max describe dispersion; neither is a confidence/prediction
interval. Median reduces sensitivity to a single extreme valid rating without
trimming or reclassifying subjective observations. An even sample produces at
most half-point increments; no extra decimal precision is invented.

No thresholds for «Привычная нагрузка», «Тяжелее обычного» or «Легче обычного»
are calibrated. v1 therefore reports numbers and above/below/equal-to-median
comparisons only, with explicit sample count, dispersion and limitations.

## Event time versus availability and edits

Candidate event start must predate target start. In addition, current raw
`updated_at`, normalized metrics `computed_at`, selected observation `received_at`
and resolution `resolved_at` must all be strictly earlier than target start.
An explicit observation `observed_at`, when present, must also predate cutoff;
its absence does not substitute for receipt time. SQL applies these guards before
LIMIT, and the pure calculator repeats the temporal/scale/owner/matching guards.
Missing availability timestamps fail closed. The target's stored effective RPE
is the observed outcome and is allowed after the session; it is not baseline
input. Future/missing target start returns unavailable.

These guards exclude late ingestion, edits and recomputations, even if the
activity itself occurred earlier. Reconciliation may update receipt/resolution
time without changing a score; conservative exclusion can therefore substantially
reduce the sample. Current tables overwrite source observations and metrics.
They cannot recover an overwritten value, an old source-resolution state or past
ownership/exclusion decisions. `as_of_reproducible=false` is always explicit.
Target metrics can also have been recomputed using revised historical FTP: this
is a retrospective comparison using current target metrics, not a reconstructed
forecast made before the target. No historical prediction evaluation may treat
this contract as a frozen as-of dataset. Existing decision snapshots do not
contain a complete versioned comparable-session evidence set; v1 does not pretend
they do. Full historical evaluation needs separately captured immutable inputs.

## Surfaces and boundaries

[Service/API contract](../api/EFFORT_DEVIATION.md). Today displays PED only in
history context after independent selection, using saved effective actual RPE,
explicitly distinct from the current draft. Missing saved RPE can retain the
expected baseline while PED remains null. Insufficient history returns null
expected/PED/dispersion with no verdict. No migrations, streams, external calls,
automatic assignment, save retries or readiness changes.
