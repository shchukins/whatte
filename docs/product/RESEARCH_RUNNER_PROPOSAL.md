# Isolated parameter experiment runner (#136)

## Implementation proposal

Use a trusted host supervisor and two sequential, bounded Docker containers:
feature-only candidate execution, then frozen evaluation against labels. A pinned
image ID/digest and fixed entrypoint are operator inputs; candidate configuration
cannot supply executable code, paths, environment variables, or metric settings.
Containers have no network, credentials, Docker socket, or production mounts.

Persist only audit metadata through a dedicated PostgreSQL writer connection.
Add nullable execution metadata to terminal records, preserving existing rows
and one-way lifecycle semantics. Store private artifacts and bounded logs outside
the repository. Duplicate experiment IDs fail rather than overwrite results.

## Explicit prerequisite

`readiness_parameter_candidate_v1` describes a recipe, not an outcome prediction
engine. Existing snapshots also lack response-baseline replay context. The built-in
candidate worker must reject these unsupported requests with a stable reason code.
Do not invent RPE/recovery mappings, disable response, or reconstruct mutable DB
history. Infrastructure tests can exercise the success protocol with synthetic
fixtures, but this does not satisfy the real-candidate acceptance criterion.

#136 remains partial until a separately reviewed prediction contract and compatible
immutable inputs make real candidate execution possible. No scheduling, search,
promotion, deployment, or production model changes belong to this implementation.

## Follow-up dependency

[Issue #150](https://github.com/shchukins/whatte/issues/150) defines and implements
the deterministic offline outcome-prediction contract and compatible immutable
inputs. Complete that dependency and a real end-to-end run before closing #136
or starting the #138 search loop. The broader product prediction layer remains #55.
