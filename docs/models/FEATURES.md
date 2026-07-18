# Features

## 1. Purpose

Этот документ описывает слой признаков (features) в Whatte.

Цель:

- определить, какие признаки извлекаются из raw данных
- зафиксировать их вычисление
- обеспечить воспроизводимость
- отделить raw данные от метрик

---

## 2. What is a feature

Feature — это производная характеристика данных, используемая для расчета метрик и моделей.

Пример:

- сглаженная мощность
- распределение по зонам
- вариативность нагрузки

---

## 3. Role in system

Features находятся между:

- raw data
- metrics

Поток:

```text
Raw data
↓
Features
↓
Metrics
↓
Readiness
```

Текущее состояние:

- базовые daily layers уже реализованы без отдельного расширенного persisted feature layer
- `daily_training_load`, normalized HealthKit tables, `health_recovery_daily`, `load_state_daily_v2` и `readiness_daily` уже работают как deterministic pipeline
- расширение feature extraction остается следующим этапом, а не обязательным условием текущего backend baseline

---

## 4. Principles

Features должны быть:

- deterministic
- воспроизводимыми
- независимыми от AI
- вычисляемыми из raw данных

---

## 5. Feature types

### 5.1 Activity-level features

Рассчитываются на уровне одной тренировки.

Примеры:

- rolling average power
- power distribution
- time in zones
- variability index

### 5.2 Stream-based features

Основаны на потоках данных:

- power stream
- heart rate stream
- cadence

Примеры:

- power smoothing
- peak values
- drift

### 5.3 Session summary features

Агрегированные признаки:

- total work
- normalized load
- intensity profile

### 5.4 Daily features

Агрегация на уровне дня:

- total load
- training density
- rest gaps

---

## 6. Example features

### 6.1 Rolling power

Сглаженная мощность:

- используется для расчета NP

### 6.2 Time in zones

Распределение времени по зонам мощности.

### 6.3 Variability Index (VI)

`VI = NP / Average Power`

Интерпретация:

- близко к 1 -> равномерная нагрузка
- выше -> интервальная нагрузка

### 6.4 Power peaks

Максимальные значения мощности на интервалах:

- 5 сек
- 1 мин
- 5 мин

---

## 7. Storage strategy

Возможные подходы:

### 7.1 Compute on demand

- считать при запросе
- не хранить

### 7.2 Persist features

- сохранять в БД
- ускорять доступ

### 7.3 Hybrid

- базовые features хранить
- сложные считать

(окончательное решение — см. `OPEN_DECISIONS.md`)

---

## 8. Relationship with metrics

Метрики используют features.

Пример:

- NP -> требует rolling power
- TSS -> требует NP, IF

---

## 9. Determinism requirement

Features должны:

- давать одинаковый результат
- не зависеть от внешних факторов
- не использовать случайность

---

## 10. Reproducibility

Для любого feature:

- можно восстановить из raw данных
- формула зафиксирована
- алгоритм определен

---

## 11. Future extensions

Планируется:

- HR features
- HRV features
- sleep-derived features
- richer activity stream features

---

## 11.5 What subjective feedback is not

`activity_subjective_feedback` is not a feature layer.

It is:

- an observed outcome layer
- a calibration / evaluation dataset
- a user-reported signal collected after the deterministic pipeline has already produced state

This distinction matters because:

- features are derived from raw inputs
- subjective feedback is reported by the athlete
- future models may train or calibrate against subjective feedback, but should not redefine feedback itself as a feature source of truth

---

## 12. Constraints

Нельзя:

- хранить только features без raw данных
- использовать AI для расчета features
- использовать нефиксированные алгоритмы

---

## 13. Debugging

Если метрики некорректны:

проверять:

1. raw данные
2. features
3. метрики

Ошибка чаще всего на уровне features.
