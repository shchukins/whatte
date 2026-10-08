# Recovery research preparation and acceptance

## Current evidence (2026-10-08)

The #150 predictor was merged and deployed at
`0aa653ae0e0f507b9cc5a9e978111879ea995740`. Backend CI
[37767788862](https://github.com/shchukins/whatte/actions/runs/37767788862)
passed unit and Docker/PostgreSQL integration jobs. Production backend health
passed after replacement; worker and PostgreSQL were not restarted.

A subsequent read-only check found five v1 feature snapshots, no v2 snapshot
and no daily-delivery decision snapshot after deployment at 11:06:07 UTC.
Natural persisted v2 capture is therefore still unverified. Do not fabricate a
delivery or backfill mutable history to obtain evidence. After the next successful
daily delivery, verify a v2 feature snapshot with the same user/date/event/reference
as its decision snapshot, cutoff <= captured_at, and the response replay capability.
An unavailable response is valid missingness; unsupported capability must stay explicit.

The read-only v2 export for train 2026-10-04 through 2026-10-06 and validation
through 2026-10-08 contained two canonical train days, both excluded with
`response_baseline_context_not_snapshotted`. Eligible train days and validation
days were both zero. The empty validation split also cannot establish the
fit-before-validation boundary. These diagnostic split dates are not a proposed
acceptance experiment. No raw physiological values or user IDs were printed.

On `human-engine-home`, read-only preflight found Docker 29.8.1, cgroup v2,
8 CPUs, approximately 32 GiB RAM and 43 GiB free on /srv. Existing containers
were running. The clean /srv/human-engine checkout was at
`be6fff0e0be7b7cd375a41a8b474fe7a24591593`; Python 3.12.3 was present, but
no backend virtualenv was found. Image/runtime preparation and audit-writer
provisioning have not been performed or verified. Keep the research checkout
separate from active application checkouts, including Tratte.

## Aggregate readiness command

From backend/, with a private JSON export made by
`scripts.export_temporal_dataset --dataset-version temporal_dataset_v2`
and without `--include-test`:

```bash
python -m scripts.report_recovery_data_readiness \
  --dataset /private-research/dataset.json \
  --fit-as-of FIT_AS_OF_ISO_TIMESTAMP
```

Use the immutable manifest's split boundaries; do not override them inside the
report. FIT_AS_OF must precede the first validation feature cutoff and follow
all included train feedback receipt timestamps. A calendar gap may be necessary
for D+1 feedback. Pick the splits and fit boundary before candidate iteration.

The command reads a bounded 64 MiB file, writes no files or database rows, fits
no coefficients, and prints aggregate JSON only. It refuses test-inclusive exports
even with an empty test list or a test-access environment grant. Exit status:
0 = ready_for_preparation, 2 = insufficient_data, 1 = invalid_dataset/input.

The report validates v2 hashes, day identities, source timestamps and temporal
boundaries through the existing evaluator. It reports canonical days, day-start
context days, compatible targets, replay missingness, train receipt violations
and sufficient train variance. Train eligibility reuses the model's training-pair
function and 30-day floor. Validation potential coverage uses baseline feature
replay and the runner's compatible-target denominator, with floors 20 days / 80%.
This is an upper bound for a candidate sharing the baseline's replayable inputs;
candidate settings can further reduce coverage. `actual_paired_coverage` remains
null until the runner evaluates both real artifacts.

Export exclusion counts are explicitly `export_exclusions_unverified`: this
metadata is outside the existing manifest hash. Only known reasons for train
and validation are printed. They diagnose collection gaps and cannot authorize
acceptance. No test target values are accessed, fitted or evaluated.

## Home-server runbook (pending operational execution)

1. Verify the first natural v2 delivery and collect enough prospective evidence.
   Export private train/validation JSON without test access and freeze its hash,
   split boundaries and fit receipt boundary. Keep directories 0700 and files 0600.
   Run the readiness command. Proceed only on ready_for_preparation; this is
   permission to prepare evidence, not proof of acceptance.
2. Use an isolated checkout at an explicitly reviewed commit containing the
   report increment. Record its exact SHA; the deployed predictor baseline is
   0aa653ae above. Do not change the active /srv/human-engine or /srv/tratte
   checkout. Install the backend requirements into a dedicated virtualenv.
   Build the worker from that same checkout and retain the immutable image ID:
   `docker build -f backend/Dockerfile.research -t whatte-research:reviewed backend`,
   then `docker image inspect --format '{{.Id}}' whatte-research:reviewed`.
   Do not use a floating tag as runner input.
3. Provision a dedicated audit LOGIN as specified in
   [RESEARCH_RUNNER.md](RESEARCH_RUNNER.md). Supply its DSN privately through
   WHATTE_RESEARCH_DATABASE_URL to the supervisor. Never use the production
   backend DSN for the runner. Provisioning is a separate operational step;
   this readiness increment has not created accounts or grants.
4. Prepare the frozen train-only affine state and baseline:

   ```bash
   python -m scripts.prepare_recovery_prediction \
     --dataset /private-research/dataset.json \
     --fit-as-of FIT_AS_OF_ISO_TIMESTAMP \
     --partition validation --output-root /private-research/prepared
   ```

   The preparation directory must not already exist. Retain dataset, learned-state,
   baseline-config and baseline-prediction hashes. First use baseline-config as
   candidate for protocol parity; then prepare a complete explicit candidate
   with the same learned_state_hash. For the reviewed weight-only example,
   change freshness_weight to 0.8 and recovery_evidence_weight to 0.2,
   preserving all other baseline fields and fixed thresholds. Validate it with
   `scripts.validate_research_config` before execution. This tests mechanics;
   it does not declare those weights optimal.
5. Run the real candidate with a unique experiment ID and immutable image ID:

   ```bash
   python -m scripts.run_research_experiment \
     --config /private-research/candidate.json \
     --dataset /private-research/dataset.json \
     --baseline /private-research/prepared/baseline-predictions.json \
     --learned-state /private-research/prepared/learned-state.json \
     --partition validation --experiment-id recovery-acceptance-001 \
     --hypothesis 'Reviewed weight-only next-day recovery comparison' \
     --image sha256:REVIEWED_IMAGE_ID --output-root /private-research/runs \
     --timeout-seconds 120 --cpus 1 --memory-mb 512 --pids 64 \
     --tmp-mb 32 --input-bytes 67108864 --output-bytes 8388608
   ```

   The fixed worker receives no credentials/network/Docker socket. Existing
   supervisor limits apply independently to candidate and evaluator containers.
   Do not run parallel experiments on the shared server for this acceptance.
6. Inspect the terminal audit/receipt: candidate status, actual paired count >=20,
   fraction >=0.8, implementation/state/baseline/image identities, bounded execution,
   container cleanup, private logs, and unchanged application services. Reproduce
   the candidate with another experiment ID and compare artifacts/metric hashes.
   MAE improvement is not required. Failed coverage is a failed acceptance.
   Keep detailed evidence private and publish only aggregate conclusions.

Closing #150/#136 requires the natural capture evidence and this sufficiently
covered real run; issue closure remains separately authorized. Only then begin
#138. No scheduler, search, production tuning or automatic promotion is added.

## Local validation

On 2026-10-08 the backend unit suite passed 503 tests; 17 integration checks
were deselected. Nine report tests cover model/preparation parity, deterministic
output, zero v2 eligibility, canonical first-activity exclusion, target/coverage
denominators, late receipts, fit embargo, variance, hashes/provenance, test denial,
malformed metadata and read-only CLI privacy. This increment adds no Docker or
SQL behavior; a home-server acceptance result is still pending.
