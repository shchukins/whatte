# AGENTS.md

## Purpose

Human Engine is an engineering-first system for analyzing training data and supporting workout decisions.

Current product priority:

> deterministic core first  
> AI is auxiliary

This file is a short entrypoint for agents. Detailed workflow, style, PR, and documentation rules live in dedicated documents.

## Mental model

Human Engine is:

- a data pipeline
- a physiology-informed model
- a readiness evaluation system
- a deterministic decision-support system

Human Engine is not:

- an AI-driven product core
- a black-box decision engine
- a generative substitute for domain logic

## Non-negotiable rules

- Do not replace deterministic logic with LLM behavior.
- Do not introduce hidden probabilistic behavior into the product core.
- Do not silently change physiology logic, metric definitions, or readiness meaning.
- Do not modify critical domain logic implicitly or without clear justification.
- Do not introduce new architecture or services without an explicit reason.

## Architecture boundaries

Protected core:

- backend
- database
- domain logic

AI is limited to auxiliary roles such as:

- explanation
- text generation
- navigation and analysis support
- documentation assistance

If a change pressures these boundaries, stop and make the boundary tradeoff explicit.

## Change philosophy

Prefer:

- minimal, explicit changes
- local reasoning
- simple designs
- deterministic, observable behavior

Avoid:

- large refactors without a clear need
- hidden coupling
- premature abstractions
- convenience-driven changes that weaken explainability

## Required reading

Before non-trivial work, read the local context that defines the system:

- `README.md`
- `docs/ai/PRODUCT_CONTEXT.md`
- `docs/ai/CURRENT_PRIORITIES.md`
- `docs/ai/GLOSSARY.md`
- `docs/ai/SYSTEM_MAP.md`

## External rule documents

Operational detail is maintained separately. Follow these documents instead of duplicating their rules here:

- `docs/ai/rules/CODEX_RULES.md`
- `docs/ai/rules/PR_WORKFLOW_RULES.md`
- `docs/ai/rules/CODE_STYLE_RULES.md`
- `docs/ai/rules/DOCUMENTATION_RULES.md`

Use them for:

- implementation and review workflow
- PR scope and process
- code comments and style expectations
- documentation update requirements

## Skills

Project skills are stored in:

- `docs/ai/skills/`

When asked to use a skill:

- open `docs/ai/skills/<skill-name>.md`
- follow its instructions
- if it does not exist, say so explicitly

## Conflict resolution

If rules conflict, use this priority:

1. deterministic correctness
2. architecture boundaries
3. simplicity
4. developer convenience
