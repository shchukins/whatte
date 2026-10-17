# Current priorities

As of 2026-10-17 (Europe/Moscow); сверено с `main` / `9013921` и GitHub issues.
Статусы реализации, тестов и production evidence: [Current state](../product/CURRENT_STATE.md).

## 1. Current phase

Whatte находится в фазе:

> эксплуатационная проверка и калибровка реализованного baseline

Основной фокус:

- сохранить предсказуемое поведение production baseline
- использовать завершенный #108 morning-loop pilot как проверяемый baseline для
  последующей оценки по исходам
- завершить evidence/операционную приёмку реализованного research path до запуска поиска
- отделять новые возможности от ожидания данных; не менять baseline без отдельного решения

---

## 2. Core principle

Главное правило:

> сначала корректная система, потом усложнение

Приоритет:

- deterministic logic
- простота
- наблюдаемость

---

## 3. What is priority NOW

### 3.1 Research critical path: implementation ≠ acceptance

Принятая зависимость из [#150](https://github.com/shchukins/whatte/issues/150)
и [acceptance runbook](../product/RECOVERY_RESEARCH_ACCEPTANCE.md):

`prospective evidence → приёмка #150/#136 → #138 → проверка research MVP → #139–#143`

- **Реализовано:** optional physiology #126–#131, outcomes #132, temporal
  snapshots/export #133, evaluator #134, audit #135, parameter space #137;
  recovery predictor #150 и инфраструктура runner #136 также имеют код и тесты.
  [#125](https://github.com/shchukins/whatte/issues/125) остаётся открытым эпиком.
- **Ожидает данных:** достаточно replayable v2 train/validation дней с
  next-day recovery. Последний специализированный acceptance record — 2026-10-08;
  более свежий [PED availability report, 2026-10-15](../product/PED_RESEARCH.md#observed-result-2026-10-15-europemoscow)
  содержит в рассмотренном окне 0 eligible train days, 2 validation rows и 1 compatible recovery target.
  Он не заменяет readiness report #150 и не доказывает достаточность данных
  на 2026-10-17. Нельзя восстановить legacy response context из mutable history.
- **Следующий шаг при отдельной операционной работе:** подтвердить natural
  delivery → v2 snapshot linkage и response replay capability по runbook;
  сохранить prospective evidence и frozen chronological boundaries. До подготовки
  run требуются ≥30 eligible train days, временная fit/receipt граница и variance
  checks. `ready_for_preparation` разрешает подготовку, а не означает приёмку.
- **Операционная приёмка после gates:** отдельно подготовить isolated home-server
  checkout/image и dedicated audit writer; реальный baseline/candidate должны
  пройти CLI → isolation → frozen evaluation → audit с ≥20 paired validation days,
  coverage ≥80%, повторяемостью и сохранёнными identities. Улучшение MAE не
  требуется; эти floors не являются доказательством статистической мощности.
- **Только после этой приёмки:** начинать
  [#138](https://github.com/shchukins/whatte/issues/138): bounded batch, фиксированная
  последовательность кандидатов, versioned validation comparison, audit failures,
  без доступа к test и без promotion. Закрытые #137/#196 или synthetic success
  не снимают зависимость от открытых [#136](https://github.com/shchukins/whatte/issues/136)
  и #150.

Отдельное ожидание данных: продолжение [PED study #196](../product/PED_RESEARCH.md)
требует prospective PED captures и достаточного cohort для frozen protocol.
Реализация завершена; польза/отсутствие пользы неизвестны. Это не снимает
блокеры #150/#136; интеграция PED в readiness требует отдельного versioned решения.

### Что можно делать сейчас независимо от накопления research-данных

Следующая очередность — **рекомендация этого обзора**, а не ранее утверждённое
продуктовое решение или разрешение на production/data operations:

1. Для [#95](https://github.com/shchukins/whatte/issues/95) и
   [#77](https://github.com/shchukins/whatte/issues/77) уточнить оставшуюся границу
   между уже реализованными descriptive analytics и validated model-error target.
   Не переопределять #150 как product-facing #55. Переход к tuning возможен лишь
   после принятой методики и достаточного evidence; текущая модель фиксирована.
2. Для [#10](https://github.com/shchukins/whatte/issues/10) подготовить критерии
   аудита первого non-cycling sport: required metrics, units, missingness,
   provenance и comparability. Выбор спорта/формулы требует отдельного аудита
   доступных данных, который здесь не проводился. Реализация — после review
   контракта; [#12](https://github.com/shchukins/whatte/issues/12) ждёт хотя бы
   одного принятого дополнительного load source. Cycling baseline не меняется.

### 3.2 Deterministic core

Критически важно:

- readiness logic должна быть явной
- recovery scoring должен оставаться прозрачным
- recommendation и briefing должны оставаться детерминированными
- никакой скрытой логики

Нельзя:

- переносить логику в LLM
- заменять формулы текстом

### 3.3 Completed scope and deferred product backlog

Не включать в новую разработку уже реализованные:

- deterministic mapping/briefing и общий persisted-readiness contract API/Telegram;
- wearable-independent composition #117/#118 и принятый #108 pilot;
- Web Today/Profile/Diary scope [#153](https://github.com/shchukins/whatte/issues/153)
  и [#169](https://github.com/shchukins/whatte/issues/169), включая effective RPE,
  pending recalculation, stale forms, lifecycle и фактическую сводку;
- optional physiology #129 и RPE guidance/history/PED #192–#195.

Broader planning [#93](https://github.com/shchukins/whatte/issues/93),
product outcome prediction [#55](https://github.com/shchukins/whatte/issues/55),
analytics [#80](https://github.com/shchukins/whatte/issues/80),
calendar/equipment и calibration #54 остаются backlog, без утверждённой здесь
очередности реализации. Nonlinear load transform и tuning readiness zones
не являются автоматическим следующим шагом после появления research-кода.

---

## 4. AI and research boundary

RAG и другие AI-инструменты рассматриваются как:

> инструмент разработчика, не продукт

### Цели:

- навигация по коду
- ответы по документации
- ускорение разработки

### Ограничения:

- не внедрять LLM в production расчёты или decision path
- будущие #139/#140 ограничены offline предложениями и проверяемыми configs
- не подменять deterministic search, evaluator или human promotion генерацией

---

## 5. Engineering workflow

### AI-assisted development

Используется как инструмент:

- анализ кода
- генерация изменений
- помощь в документации

Но:

- с обязательной проверкой
- без внедрения AI в deterministic core

---

## 6. Knowledge management

Репозиторий = источник истины

Не хранить знания в чатах.

Обязательно фиксировать:

- продуктовый контекст
- архитектуру
- модели
- решения

---

## 7. Technical direction

### Backend

- простые сервисы
- явные зависимости
- минимальная магия
- separate storage layers for load, recovery, readiness

### Data

- надежный ingestion
- хранение raw данных
- движение к воспроизводимости

### Current modeling focus

- стабилизация `load_state_daily_v2`
- стабилизация `health_recovery_daily`
- стабилизация `readiness_daily`
- стабилизация wearable-independent `v2_signal_composition_response_v1` и его
  signal-family contract
- стабилизация versioned `activity_response_metrics` и comparable-session baseline
- стабилизация deterministic `decision_engine` и briefing contract поверх readiness
- сохранять общий `decision_engine` contract при развитии presentation wrappers
- calibration только после evidence/приёмки и отдельного versioned решения;
  personal baselines, offline fitting и PED не доказывают calibrated probability

---

## 8. Decision rules

Если возникает выбор:

Предпочитать:

1. простое решение вместо сложного
2. явную логику вместо скрытой
3. детерминированность вместо black-box вероятности
4. локальные изменения вместо глобальных

Избегать:

- overengineering
- premature abstraction
- внедрения AI "потому что можно"

---

## 9. Definition of progress

Прогресс — это не количество фич.

Прогресс — это:

- система стала понятнее
- логика стала прозрачнее
- поведение стало стабильнее

---

## 10. Next milestone

Следующий research milestone — **приёмка #150/#136**, затем проверяемый
bounded search #138. Критерии перехода определены в
[recovery acceptance](../product/RECOVERY_RESEARCH_ACCEPTANCE.md),
[recovery predictor](../models/RECOVERY_PREDICTION.md) и
[runner contract](../product/RESEARCH_RUNNER.md).

#108 pilot и shared decision delivery уже реализованы и не являются будущими
milestones. Research infrastructure не равна принятому research MVP; deploy
не равен достаточности данных. После #138 требуется отдельная оценка pipeline
перед LLM #139/#140; registry/manual promotion #141, scheduler #142 и summary
view #143 остаются последующими задачами #125. Никакой этап автоматически не
разрешает изменения production readiness или признаёт `good_day_probability`
откалиброванной вероятностью.
