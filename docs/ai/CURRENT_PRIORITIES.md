# Current Priorities

## 1. Current phase

Human Engine находится в фазе:

> стабилизация и согласование реализованного baseline

Основной фокус:

- убрать устаревшие описания
- сделать поведение системы предсказуемым
- зафиксировать архитектурные границы

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

### 3.1 Backend stabilization

- удержать deterministic core стабильным
- не размывать текущую architecture baseline
- улучшать только подтвержденные backend layers

Backend должен выполнять:

- ingestion
- хранение данных
- deterministic расчеты
- API

### 3.2 Deterministic core

Критически важно:

- readiness logic должна быть явной
- recovery scoring должен оставаться прозрачным
- ride briefing, если появится, должен быть детерминированным
- никакой скрытой логики

Нельзя:

- переносить логику в LLM
- заменять формулы текстом

### 3.3 Architecture boundaries

Жесткое разделение:

Core:

- backend
- postgres
- доменная логика

AI:

- отдельный слой
- не влияет на расчеты

---

## 4. RAG (experimental direction)

RAG рассматривается как:

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

- HealthKit full-sync стабильно проходит end-to-end
- load / recovery / readiness layers детерминированы и согласованы
- probability layer явно описан как baseline mapping
- документация отражает реальное состояние системы

После этого можно:

- калибровать readiness / probability
- добавлять decision layer поверх текущего baseline
