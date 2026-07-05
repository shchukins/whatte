# START HERE

## Purpose

Human Engine is a deterministic training decision support system.

The goal is to recommend the right training on the right day using measurable physiological signals. AI assists with explanation and implementation but must not replace deterministic decision logic.

---

## Before starting any task

1. Understand the user's request.
2. Read only the documentation relevant to the task.
3. Search for existing implementations before creating new ones.
4. Reuse existing architecture whenever possible.
5. Propose a short implementation plan.
6. If the task affects architecture or public APIs, wait for approval before making changes.

---

## Source of truth

Project overview:
- README.md

Architecture:
- docs/architecture/ARCHITECTURE.md
- docs/ai/SYSTEM_MAP.md

Current product direction:
- docs/ai/CURRENT_PRIORITIES.md
- docs/ai/CURRENT_FOCUS.md
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
