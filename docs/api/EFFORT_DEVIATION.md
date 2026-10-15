# Personal effort deviation contract v1

`get_effort_deviation(user_id, activity_id)` returns the versioned read-only
`personal_effort_deviation_v1` contract. [Method and temporal limitations](../models/PERCEIVED_EFFORT_DEVIATION.md).

`GET /today/effort-deviation/{activity_id}` returns JSON under the existing Today
edge authentication/configured-athlete boundary. No user ID parameter is used.
Only owned, canonical, non-deleted/non-excluded targets are readable; others
return 404. Invalid ID returns 422, read failure 503. Responses use
`Cache-Control: no-store`. This route never submits or assigns RPE.

Fields:

- `version`, `status` (`available|unavailable`), `computed_at` (UTC).
- `actual_rpe`: saved effective score in the eligible scale, otherwise null.
- `expected_rpe`: median when baseline has at least three eligible matches,
  otherwise null; may be available without actual RPE.
- `ped`: actual minus expected, or null unless both are available.
- `sample_count`: selected eligible comparable rows, including counts below three.
- `baseline`: version, median method, matching version, 365-day window,
  maximum 200 candidates/five matches, minimum three samples, original scale
  and eligible sources.
- `dispersion`: `method=median_absolute_deviation`, `mad`, observed `range`,
  or null when baseline unavailable.
- `reliability`: `limited` with usable baseline, otherwise `unavailable`.
- `comparison`: `above_median|below_median|at_median`, or null. These describe
  arithmetic sign, not calibrated exertion/recovery categories.
- `source_references`: selected session IDs, event timestamps, RPE, original
  source/scale, matching quality and availability timestamps. Even an insufficient
  sample retains references for audit. `actual_reference` identifies the stored
  outcome separately; target matching quality is null.
- `evidence_cutoff_at`: target start; `as_of_reproducible=false`.
- `limitations`: missing interval structure, small selected sample, mutable
  records, possibly recomputed target metrics and no causal recovery inference.
- `reason_codes`: insufficient prior available comparable sessions,
  missing/incompatible actual score, or missing/future target time.

All timestamps serialize as ISO 8601. The target rating is an outcome, not prior
baseline evidence. Candidate availability is checked strictly before target start,
not merely before current computation time. No source rescales or fallback
reconstruction are performed.

The existing `/today/rpe-context/{id}` HTML response also includes a PED section
following independent selection; it labels saved RPE and does not use draft
`score` as actual. A PED read failure leaves history and explicit save usable.
Initial Today renders neither historical ratings nor a PED reference.
