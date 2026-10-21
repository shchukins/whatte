# Architecture Decisions

Этот документ фиксирует ключевые архитектурные решения в Whatte.

Цель:

- сохранить контекст решений  
- избежать повторного обсуждения  
- обеспечить согласованность развития системы  

---

## ADR-001: Deterministic Core First

**Status:** accepted  

### Context

Система должна оценивать состояние человека и давать рекомендации по тренировкам.

Использование LLM в core логике:

- делает поведение непредсказуемым  
- усложняет отладку  
- нарушает воспроизводимость  

---

### Decision

Core системы строится как детерминированный:

- явные формулы  
- явные модели  
- никакой генеративной логики  

---

### Consequences

- система предсказуема  
- проще тестировать  
- сложнее на старте (меньше "магии")  

---

## ADR-002: AI as Auxiliary Layer

**Status:** accepted  

### Context

AI может ускорять разработку и улучшать UX, но:

- не должен управлять логикой системы  
- не должен принимать решения  

---

### Decision

AI используется только для:

- генерации текста  
- объяснений  
- работы с документацией  

AI не участвует в:

- расчетах  
- readiness  
- рекомендациях  

---

### Consequences

- архитектура остается чистой  
- AI легко отключить  
- меньше "вау-эффекта" на раннем этапе  

---

## ADR-003: Remove AI from Backend Runtime

**Status:** accepted  

### Context

Изначально AI был встроен в backend:

- Ollama  
- AI endpoints  
- RAG внутри backend  

Это привело к:

- усложнению системы  
- замедлению разработки  
- смешению ответственности  

---

### Decision

Удалить AI из backend runtime:

- убрать Ollama  
- удалить AI endpoints  
- вынести AI в отдельный слой  

---

### Consequences

- backend стал проще  
- быстрее разработка  
- AI можно развивать отдельно  

---

## ADR-004: Self-hosted Infrastructure

**Status:** amended  

### Context

Требования:

- контроль над данными  
- независимость от внешних сервисов  
- гибкость  

---

### Decision

Изначальное решение:

- home server  
- VPS как gateway  
- Tailscale для сети  

Текущая production-схема после VPS migration:

- production backend работает на VPS
- Caddy обслуживает `shchukin.de/dashboard` и `api.shchukin.de`
- старый home-server runtime / watchdog monitoring считается legacy context, а не основной production topology

---

### Consequences

- полный контроль  
- больше ответственности за инфраструктуру  
- сложнее масштабирование  

---

## ADR-005: Raw Data Preservation

**Status:** accepted  

### Context

Для корректных моделей необходимо:

- возможность пересчитать метрики  
- проверять данные  

---

### Decision

Всегда сохранять raw данные:

- без изменений  
- с возможностью повторного использования  

---

### Consequences

- воспроизводимость  
- больше объем хранения  
- проще отладка  

---

## ADR-006: Simple Architecture First

**Status:** accepted  

### Context

Сложные архитектуры на раннем этапе:

- замедляют разработку  
- увеличивают количество ошибок  

---

### Decision

Избегать:

- микросервисов  
- лишних abstraction layers  

Строить:

- простую, понятную систему  

---

### Consequences

- быстрее развитие  
- легче понимать систему  
- возможен рефакторинг позже  

---

## ADR-007: RAG as Developer Tool

**Status:** accepted  

### Context

RAG может быть полезен:

- для навигации по коду  
- для документации  

Но:

- не должен быть частью продукта на данном этапе  

---

### Decision

Использовать RAG:

- локально  
- вне backend  
- как инструмент разработчика  

---

### Consequences

- ускорение разработки  
- отсутствие зависимости от RAG  
- чистая архитектура продукта  

---

## ADR-008: Goal-directed training decisions under time constraints

**Status:** accepted product direction, 2026-10-21; implementation planned.

### Context

The current readiness-to-category baseline describes today's state but does not
choose between useful workouts when real available time differs from a plan.
Further physiological precision alone does not close this product gap.

### Decision

Preserve “What is today?” and evaluate today's choice within the week and block.
Use long-term, goal-relevant sporting progress as the outcome; readiness and
recovery are supporting constraints/context, not optimization targets.
Start with one cyclist, a manual plan and changing available time, using explicit
deterministic rules and a comparison to a simple baseline.

[Product context](../ai/PRODUCT_CONTEXT.md) defines the direction;
[Training decision MVP](../product/TRAINING_DECISION_MVP.md) bounds the experiment.

### Consequences

- Readiness formulas, API/storage contracts and current runtime stay unchanged.
- Calibration, recovery prediction and autoresearch expansion are paused
  priorities; their acceptance is not a dependency of this MVP.
- Preserve their code, documentation, raw inputs and evidence gates for any
  separately approved resumption.
- Goal/plan/constraint/adaptation responsibilities do not imply new services.
- No automatic periodization, precise adaptation forecast or LLM decision core.
- Product and sporting outcomes are assessed separately; one-user progress
  cannot establish causal superiority.

## How to add new decisions

При добавлении нового решения:

1. создать новый ADR  
2. описать контекст  
3. явно зафиксировать решение  
4. указать последствия  

Не изменять старые ADR, если решение уже принято.
