# Product Context

## 1. What Human Engine is

Human Engine — система анализа тренировочных данных и состояния человека.

Система:

- собирает данные о тренировках
- собирает recovery-сигналы
- оценивает физиологическое состояние
- рассчитывает readiness
- помогает выбрать нагрузку

Ключевая идея:

> правильная тренировка в правильный день

---

## 2. System role

Human Engine — это не просто хранилище данных.

Это:

- decision-support system
- physiology-driven model
- reproducible analytics pipeline

Система должна:

- давать объяснимые результаты
- работать детерминированно
- быть проверяемой

---

## 3. What the product is NOT

Human Engine не является:

- просто тренировочным логом
- визуальным дашбордом без логики
- AI-тренером
- black-box системой
- системой, где решения принимаются LLM

AI не должен становиться ядром системы.

---

## 4. Core architecture principle

Система строится вокруг разделения:

### Deterministic core

- ingestion данных
- raw и normalized storage
- расчет метрик
- recovery logic
- readiness logic
- probability mapping

Требования:

- явная логика
- воспроизводимость
- проверяемость

### AI layer (auxiliary)

AI может использоваться для:

- генерации текста
- объяснения метрик
- навигации по документации
- помощи разработчику

AI не участвует в:

- расчете метрик
- принятии решений
- изменении доменной логики

---

## 5. Current product focus

Текущий этап:

- стабилизация deterministic backend baseline
- поддержание архитектуры Model V2
- фиксация документации по реализованному состоянию
- формирование надежного end-to-end data pipeline

Система должна сначала стать:

- корректной
- предсказуемой
- устойчивой

и только потом — умной.

---

## 6. Data -> Model -> Decision flow

Общий поток:

Data ingestion  
↓  
Raw / normalized storage  
↓  
LoadState + RecoveryState  
↓  
Readiness  
↓  
GoodDayProbability  
↓  
Recommendation

Этот поток должен оставаться:

- прозрачным
- трассируемым
- воспроизводимым

Текущее реализованное состояние:

- HealthKit ingestion и full-sync уже работают в backend
- recovery и readiness уже materialized как отдельные daily layers
- baseline decision / recommendation layer уже реализован как deterministic mapping поверх `readiness_daily`
- более широкий recommendation / planning layer остается planned

---

## 7. Design constraints

При развитии системы:

Нельзя:

- заменять детерминированную логику LLM
- вводить скрытые вычисления
- смешивать AI и core-логику
- усложнять архитектуру без необходимости

Можно:

- упрощать
- делать явные модели
- улучшать наблюдаемость
- добавлять проверяемость

---

## 8. Expected behavior of contributors / AI

Любые изменения должны:

- сохранять deterministic core
- не нарушать архитектурные границы
- быть объяснимыми
- быть проверяемыми

Если возникает сомнение:

предпочтение всегда отдается простой и явной логике.
