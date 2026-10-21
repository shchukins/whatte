# START HERE

## Purpose

Whatte is a deterministic training decision support system.

The product goal is to help choose today's most useful workout given the block
goal, actual training and available time across the week. Long-term progress is
the outcome; readiness is supporting context. The implemented baseline still maps
readiness to a category. Time-aware adaptation is planned:
[bounded MVP](../product/TRAINING_DECISION_MVP.md).
AI assists with explanation and implementation but must not replace deterministic
decision logic. Recovery research and calibration expansion are paused product
priorities, not prerequisites for the MVP.

---

## Before starting any task

1. Understand the user's request.
2. Read only the documentation relevant to the task.
3. Search for existing implementations before creating new ones.
4. Reuse existing architecture whenever possible.
5. State a short, bounded implementation plan when scope is ambiguous or
   crosses an architecture or public-API boundary.
6. Verify affected behavior with tests or an equivalent focused check.

---

## Source of truth

Project overview:
- README.md

Architecture:
- docs/architecture/ARCHITECTURE.md
- docs/ai/SYSTEM_MAP.md

Current product direction:
- docs/ai/CURRENT_PRIORITIES.md
- docs/ai/PRODUCT_CONTEXT.md

Terminology:
- docs/ai/GLOSSARY.md

Project rules:
- AGENTS.md
- docs/ai/rules/

---

## Development principles

- Prefer small, incremental changes.
- Keep solutions simple.
- Avoid duplicate logic.
- Maintain explainability.
- Preserve backward compatibility unless explicitly requested.
- Update documentation whenever behavior changes.
- Write or update tests when appropriate.

---

## Do not

- Invent product requirements.
- Invent physiological models or formulas.
- Introduce unnecessary abstractions.
- Perform large refactorings without approval.
- Modify infrastructure or deployment unless requested.
- Ignore existing project conventions.

---

## Definition of Done

A task is considered complete only when:

- Implementation is finished.
- Tests pass (when applicable).
- Documentation is updated (when required).
- No obvious regressions remain.
- The implementation follows existing project architecture.

When uncertain, ask rather than assume.
