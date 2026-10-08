# User profile Web contract

All routes are under protected `/today*`, use the configured
`DAILY_READINESS_USER_ID`, and accept no user selector. Caddy blocks `/today*`
on the technical API domain. Keep the backend private behind that edge.

- `GET /today/profile`: HTML with current values, history and pending status.
- `POST /today/profile`: URL-encoded form with `metric` (`ftp`, `hr_max` or `weight`),
  `value` and `effective_from` (`YYYY-MM-DD`). Success redirects with HTTP 303.
  Validation errors render HTML with HTTP 422; other content types return 415.
- `POST /today/profile/recompute`: synchronous recalculation using stored data;
  success returns HTML with the number of processed activities. Failures return
  503 and explain partial progress/retry. Pending state remains persisted.
- Concurrent profile writes/recalculations return 409. Cross-site submissions
  are rejected with 403 using the existing Web Today origin/fetch-site guard.

This is a native Web form contract, not a public multi-user profile API.
See [behavior and deployment](../product/USER_PROFILE.md).

HR max accepts whole numbers from 1 to 250 bpm. These are input sanity limits,
not scoring thresholds. HR max edits schedule recomputation to refresh stored
activity provenance; power and HR zone boundaries remain independent.
