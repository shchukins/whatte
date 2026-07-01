# Open Decisions

Этот документ фиксирует архитектурные и продуктовые вопросы,
которые еще не имеют окончательного решения.

Цель:

- сохранить контекст размышлений
- отделить уже реализованное от еще не решенного
- поддерживать осознанное развитие системы

---

## OD-001: Readiness calibration

### Context

Базовая структура readiness в model v2 уже реализована:

- `LoadState + RecoveryState -> Readiness -> GoodDayProbability`
- load state использует `fitness`, `fatigue_fast`, `fatigue_slow`, `fatigue_total`, `freshness`
- recovery state использует sleep / HRV / resting HR / weight aggregates
- readiness baseline использует формулу `0.6 * freshness_norm + 0.4 * recovery_score_simple`

Но все еще не определены окончательно:

- калибровка весов
- калибровка status thresholds
- калибровка probability interpretation

---

### Options

1. Оставить текущую baseline formula и калибровать пороги
2. Расширить readiness input через `sleep_score_simple`, `hrv_dev`, `rhr_dev`
3. Ввести более явное versioning readiness calibration

---

### Open questions

- как калибровать веса без black-box логики
- какие thresholds считать стабильными для user-facing layer
- как versioning readiness model отражать в storage и docs

---

### Status

partially resolved

---

## OD-002: Feature layer expansion

### Context

Базовый feature / derived layer уже частично реализован:

- `daily_training_load`
- HealthKit normalized tables
- `health_recovery_daily`

Открытым остается вопрос расширения feature layer и его границ.

---

### Options

1. SQL-based aggregates
2. Python pipeline
3. Гибрид

---

### Open questions

- где хранить дополнительные derived features
- как делать массовый перерасчет
- как versioning расширенных features отражать в storage

---

### Status

partially resolved

---

## OD-003: Prediction model

### Context

Система предполагает прогноз:

- как тренировка повлияет на состояние

Но предиктивная модель пока не реализована.

---

### Options

1. Простая эвристика
2. Физиологическая модель
3. ML-подход

---

### Open questions

- нужен ли ML вообще
- как валидировать прогноз
- какие метрики использовать

---

### Status

open

---

## OD-004: Multi-source data strategy

### Context

Сейчас уже используются:

- Strava
- HealthKit

Следующий уровень сложности:

- расширение источников
- source priority
- conflict resolution

---

### Options

1. Strava + HealthKit как основная схема
2. Добавление новых источников с явным source priority
3. Multi-source aggregation с правилами консолидации

---

### Open questions

- что считать источником истины для пересекающихся метрик
- как синхронизировать даты и timezone-sensitive данные
- как решать конфликты при расширении источников

---

### Status

partially resolved

---

## OD-005: Ride briefing format

### Context

Ride briefing — важный output системы.

Что уже реализовано:

- baseline deterministic `recommendation`
- baseline deterministic `reason`
- baseline deterministic `briefing`
- readiness API response с decision output

Что остается незафиксированным окончательно:

- окончательный multi-surface формат user-facing briefing
- уровень детализации на разных surfaces
- граница между `decision_engine` и legacy notification formatting

---

### Options

1. Короткий structured block
2. Rule-based briefing with explanation templates
3. Более подробный plan layer поверх deterministic core

---

### Open questions

- насколько детализирован должен быть вывод
- какие ограничения выводить первыми
- как не потерять детерминированность

---

### Status

partially resolved

---

## OD-008: Decision formatting unification

### Context

В текущем backend уже есть явный `decision_engine` для recommendation / briefing.

Одновременно часть legacy notification formatting logic продолжает жить в `notification_service`.

Это не нарушает boundary между AI и deterministic core, но создает риск постепенного drift:

- тексты могут начать расходиться
- пороги и формулировки могут дублироваться
- ответственность decision layer станет менее явной

### Minimal correction strategy

1. Считать `decision_engine` canonical source для readiness-to-guidance mapping
2. Постепенно свести user-facing readiness wording к одному formatting path
3. Оставить `notification_service` orchestration-слоем, а не вторым decision-слоем

### Open questions

- какие notification-specific embellishments допустимы вне canonical decision path
- нужно ли выделять отдельный formatter module между decision и delivery
- как покрыть унификацию tests без избыточной связанности

### Status

open

---

## OD-006: UI / Visualization layer

### Context

Visualization layer пока не является основной частью реализованного product core.

Operational clarification:

- internal FastAPI SSR dashboard at `shchukin.de/dashboard` is already implemented as a read-only monitoring surface
- this open decision is about future product/user visualization, not the existing operational dashboard

---

### Options

1. Product web dashboard
2. Mobile-first
3. Минималистичный readiness-first интерфейс

---

### Open questions

- что показывать в первую очередь
- какие метрики критичны
- как не превратить систему в dashboard без решения

---

### Status

open

---

## OD-007: Storage strategy for derived data

### Context

Уже существуют derived данные:

- normalized health tables
- `health_recovery_daily`
- `load_state_daily_v2`
- `readiness_daily`

Но еще не зафиксирована общая стратегия:

- что хранить постоянно
- что пересчитывать
- как versioning делать единообразно

---

### Options

1. Хранить все derived layers
2. Пересчитывать часть state on demand
3. Гибрид

---

### Open questions

- баланс storage vs compute
- как обеспечивать консистентность между слоями
- как оформлять versioning derived tables

---

### Status

open

---

## OD-008: AI reintroduction strategy

### Context

AI остается вне deterministic core.

Возможный будущий use-case:

- explainability
- documentation
- structured summaries

---

### Options

1. Только RAG
2. AI как explainability слой
3. Ограниченные AI endpoints вне core

---

### Open questions

- где проходит граница допустимого
- как не нарушить deterministic core
- какие use-cases действительно полезны

---

### Status

deferred

---

## Lifecycle

`open -> decision -> ADR`

После принятия решения:

- перенос в `ARCHITECTURE_DECISIONS.md`
- обновление архитектуры и data/model docs
