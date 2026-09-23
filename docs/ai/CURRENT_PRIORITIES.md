# Current priorities

## 1. Current phase

Whatte находится в фазе:

> эксплуатационная проверка и калибровка реализованного baseline

Основной фокус:

- сохранить предсказуемое поведение production baseline
- использовать завершенный #108 morning-loop pilot как проверяемый baseline для
  последующей оценки по исходам
- устранить документированные расхождения между decision и delivery слоями

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

### 3.1 Evidence before model changes

- опираться на завершенный разбор #108 pilot с явными знаменателями и
  ограничениями измеримости
- определить цели, окна сравнения и метод оценки исходов в #95 до обсуждения
  изменения весов, порогов или смысла readiness
- хранить контекст решения и feedback как evidence, а не как скрытую
  онлайн-адаптацию

Backend baseline уже выполняет:

- ingestion
- хранение данных
- deterministic расчеты
- API

### 3.2 Deterministic core

Критически важно:

- readiness logic должна быть явной
- recovery scoring должен оставаться прозрачным
- recommendation и briefing должны оставаться детерминированными
- никакой скрытой логики

Нельзя:

- переносить логику в LLM
- заменять формулы текстом

### 3.3 Product gaps with bounded scope

Жесткое разделение:

- свести Telegram formatting к shared `decision_engine` contract;
- определить один поддерживаемый non-cycling Strava load slice до расширения
  multisport coverage;
- не выводить optional physiology, source freshness или unsupported load как
  нормальные/нулевые данные.

---

## 4. AI and research boundary

RAG и другие AI-инструменты рассматриваются как:

> инструмент разработчика, не продукт

### Цели:

- навигация по коду
- ответы по документации
- ускорение разработки

### Ограничения:

- не интегрировать в backend
- не использовать для принятия решений
- не делать user-facing feature

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
- устранение дублирования recommendation / briefing logic между `decision_engine` и legacy notification formatting
- readiness / probability calibration как следующий шаг, а не новый black-box слой

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

Система считается готовой к следующему этапу, когда:

- 14-day pilot имеет полный, интерпретируемый report и зафиксированные
  решения о качестве/калибровке;
- delivery surfaces используют один persisted readiness/decision contract;
- документация отражает реализованные, historical и planned границы;
- first non-cycling load work имеет отдельный согласованный contract, либо
  не начато.

После этого можно:

- калибровать readiness / probability по зафиксированной методике;
- добавлять только подтверждённые planning capabilities поверх текущего
  baseline.
