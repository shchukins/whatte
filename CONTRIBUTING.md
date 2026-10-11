# Contributing to Whatte

## Principles
- Keep things simple
- Prefer clarity over complexity
- Build incrementally (MVP first)

## Issues
- All work starts with an issue
- Use issue templates
- Clearly describe problem and solution

## Git workflow
- Default: `Issue → Codex → Tests → Commit → Push main → CI/CD`.
- Work directly on `main` when the environment permits it; create branches or
  worktrees only when explicitly requested or required by the environment.
- Preserve existing uncommitted work. Run relevant checks before small, scoped
  commits with a plain issue reference, for example `docs: clarify workflow (#186)`.
- Push to `origin/main` when requested. Never force-push, rewrite published history
  or bypass repository protections.
- PRs require explicit instruction. When requested, keep one increment per PR,
  explain what and why, link the issue and include validation results.
- See [Git and optional PR rules](docs/ai/rules/PR_WORKFLOW_RULES.md) for local/cloud
  limitations, publication checks and issue completion requirements.

## Production delivery
- Centralized CI/CD is planned and not activated. During the transition, manual
  delivery requires explicit authorization and successful CI for the exact SHA.
- Once centralized CI/CD is available, use it instead of manual production deploy.
- Do not activate automatic deploy or issue closure before prerequisites are
  implemented, tested and explicitly approved. See
  [production delivery](docs/architecture/PRODUCTION_DELIVERY.md).

## Code
- Keep backend logic deterministic
- Do not put business logic into LLM layer
- Write clear and readable code

## Documentation
- Update docs when adding new models or features
