# Git and optional pull requests

## Default workflow

`Issue → Codex → Tests → Commit → Push main → CI/CD`

Work directly on `main` when the execution environment permits it. Feature
branches and worktrees are exceptions: create them only when explicitly requested
or required by the environment. Create a PR only with explicit user instruction.
An issue starts the work; a PR is optional, not a prerequisite for delivery.

1. Inspect `git status`, the current branch and local commits before editing.
   Fetch `origin/main` when access is available and compare histories. Preserve
   existing uncommitted changes and unrelated commits; do not reset, clean, stash
   or publish them merely to make the task fit the default workflow.
2. If the checkout is clean and `main` is only behind upstream, update with a
   fast-forward. If the checkout has unrelated work, is on another branch, is
   detached or has diverged, inspect the reason before changing Git state. Do not
   switch/reset it blindly or create a branch/worktree for convenience.
3. Implement one logically complete increment. Run relevant tests before commit;
   documentation-only changes need link, consistency and whitespace checks.
   Review the diff and stage only task-owned files/hunks.
4. Use small, logically scoped commits with a plain issue reference, for example
   `feat(recovery): support manual physiology observations (#158)`. Avoid closing
   keywords such as `Fixes` or `Closes` when closure must wait for production
   verification; a pushed commit is not production acceptance.
5. Push completed changes to `origin/main` when requested, after checking that
   the outgoing commits contain only authorized work. Never force-push, rewrite
   published history, disable protections or use administrative bypasses. If
   upstream moved or GitHub rejects the push, inspect and report the cause; resolve
   it without overwriting history. If a protection requires a PR, explain that
   requirement and obtain explicit PR instruction instead of bypassing it.
6. Verify CI for the exact published SHA. Report failed or unavailable checks
   accurately; local tests do not substitute for failed required CI.

## Local and cloud execution environments

A writable local checkout on `main` with remote access can use the default path
directly. Verify the actual checkout and permissions on each task.

A cloud environment may supply an isolated branch, detached checkout or managed
worktree, or lack push credentials/network access. Treat these as environment
constraints, not a reason to create additional branches or PRs automatically.
Work in the supplied checkout when safe, run available checks and report its
branch/SHA, limitations and remaining publication steps. Never claim `main` was
updated without verifying it. Returning a patch/commit for application to local
`main` is a valid handoff; PR creation still requires explicit instruction.

Repository protection compatibility is checked live before publication. A
protection requirement takes precedence over the default direct-push path; the
workflow does not authorize weakening that requirement.

## Optional PRs

- Для аналитики, ревью и предложений сначала создавать markdown proposal, а не менять код.
- Если задача только исследовательская — не менять repo без подтверждения.
- Один PR = один законченный смысловой инкремент.
- Не смешивать независимые изменения кода, документации, issue migration и refactoring в одном PR; относящиеся к изменению docs и tests входят в его scope.
- Перед явно запрошенным PR обязательно: git status, summary изменений, risks, tests.
- Не закрывать и не переименовывать issue массово без отдельного подтверждения.

## Transitional production delivery and activation guard

Current state: CI, immutable releases, versioned migrations and centralized manual
Actions delivery are implemented. #189 validated restricted connectivity, dry run
and the authorized initial production rollout. Unattended push deployment remains
disabled pending separate operator approval; automatic issue closure remains #190.
Use [the delivery runbook](../../../ops/deploy/README.md). The audit and activation
boundaries are described in [production delivery](../../architecture/PRODUCTION_DELIVERY.md)
and epic #184. These rules do not activate unattended deployment or issue closure.

Until centralized CI/CD is available, an explicitly authorized operator may use
the audited manual path after successful CI for the exact selected SHA, schema
review and a clean server checkout. Verify that the delivered SHA is the tested
and authorized SHA. Documentation-only delivery can fast-forward the server
checkout and verify file contents without rebuilding/restarting app services.
Runtime changes require the relevant service rollout and production checks.

When centralized CI/CD is available, use it instead of manual production deploy.
Risky operations retain their explicit approval gates. Do not enable automatic
production deployment or automatic issue closure until all prerequisite components
are implemented, tested and explicitly approved for activation.

Close individual issues only when requested and their acceptance evidence is
complete. For runtime changes, wait for successful production verification;
documentation/research issues use their own validation and any requested server
documentation delivery. Do not treat push, green CI or checkout SHA alone as proof
of a running release. Record the exact commit, check results and delivery evidence.
