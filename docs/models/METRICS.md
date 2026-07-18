# Metrics

## 1. Purpose

Этот документ описывает текущие базовые метрики Whatte.

Цель:

- зафиксировать формулы
- обеспечить воспроизводимость
- синхронизировать документацию с текущим backend baseline

---

## 2. Principles

Все метрики должны быть:

- deterministic
- объяснимыми
- воспроизводимыми

Нельзя:

- использовать скрытые формулы
- менять определения без фиксации

---

## 3. Activity-level metrics

### 3.1 Duration

Время тренировки.

---

### 3.2 Average Power

Средняя мощность.

---

### 3.3 Normalized Power (NP)

Оценка физиологической стоимости переменной нагрузки.

---

### 3.4 Intensity Factor (IF)

`IF = NP / FTP`

---

### 3.5 Training Stress Score (TSS)

`TSS = (Duration × NP × IF) / (FTP × 3600) × 100`

---

## 4. Daily metrics

### 4.1 Daily Training Load

Сумма TSS за день.

---

### 4.2 Load Input

Для `load_state_daily_v2` дневная нагрузка подается через поле `load_input_nonlinear`.

Текущее состояние backend:

- функция называется `load_input_nonlinear`
- фактическая baseline-реализация использует линейный input:

```text
load_input_nonlinear = TSS
```

Нелинейная трансформация остается возможным следующим шагом, но сейчас в коде не применяется.

---

### 4.3 Fitness

Долгосрочная адаптационная компонента.

Экспоненциальное обновление:

```text
fitness[d] = fitness[d-1] + (load_input[d] - fitness[d-1]) / 40
```

---

### 4.4 Fatigue Fast

Быстрая компонента усталости.

```text
fatigue_fast[d] = fatigue_fast[d-1] + (load_input[d] - fatigue_fast[d-1]) / 4
```

---

### 4.5 Fatigue Slow

Более медленная компонента усталости.

```text
fatigue_slow[d] = fatigue_slow[d-1] + (load_input[d] - fatigue_slow[d-1]) / 9
```

---

### 4.6 Fatigue Total

В текущей Model V2 это не сумма, а взвешенная смесь:

```text
fatigue_total = 0.65 * fatigue_fast + 0.35 * fatigue_slow
```

---

### 4.7 Freshness

```text
freshness = fitness - fatigue_total
```

---

### 4.8 Calendar continuity

`load_state_daily_v2` считается по непрерывной календарной оси.

Это означает:

- в модели присутствуют и тренировочные, и нетренировочные дни
- в дни без тренировки используется `tss = 0`

---

## 5. Recovery metrics

### 5.1 Recovery Daily Inputs

Текущий recovery layer использует:

- `sleep_minutes`
- `resting_hr_bpm`
- `hrv_daily_median_ms`
- `weight_kg`

---

### 5.2 Recovery Score Simple

`recovery_score_simple` — текущее имя поля baseline recovery score из `health_recovery_daily`.

Свойства:

- диапазон `0..100`
- считается из сна, resting HR и HRV
- уже использует baseline HRV и baseline resting HR, если они доступны
- breakdown сохраняется в `recovery_explanation_json`

---

## 6. Readiness (Model V2 baseline)

Readiness — ключевая метрика системы.

В current backend readiness:

- не равна `freshness`
- считается из `load_state + recovery_state`
- хранится в `readiness_daily`

### 6.1 Freshness normalization

Перед объединением с recovery-контуром `freshness` переводится в грубую шкалу `0..100`:

```text
freshness_norm = clamp(50 + freshness, 0, 100)
```

### 6.2 Baseline formula

```text
readiness_score_raw = 0.6 * freshness_norm + 0.4 * recovery_score_simple
```

Fallback behavior:

- если нет recovery, readiness опирается на `freshness_norm`
- если нет load, readiness опирается на `recovery_score_simple`

### 6.3 Readiness score

```text
readiness_score = clamp(round(readiness_score_raw, 1), 0, 100)
```

### 6.4 Good Day Probability

Текущий probability layer в backend:

```text
good_day_probability = readiness_score / 100
```

Это baseline-мэппинг, а не откалиброванная вероятностная модель.

---

## 7. Status mapping

Текущий `status_text` определяется по `readiness_score`:

- `0..24` -> `Высокая усталость`
- `25..44` -> `Нагрузка`
- `45..64` -> `Нормальная готовность`
- `65..84` -> `Хорошая готовность`
- `85..100` -> `Очень свежий`

---

## 8. Constraints

Метрики должны:

- быть пересчитываемыми
- использовать raw и normalized upstream data
- не зависеть от AI

---

## 9. Future extensions

Планируется добавить:

- нелинейную трансформацию load input
- возможное прямое использование `sleep_score`
- возможное прямое использование `hrv_dev`
- возможное прямое использование `rhr_dev`
- уточненную калибровку probability / readiness zones

Но:

- только с явным versioning
- без потери прозрачности

---

## 10. Versioning

Сейчас versioned daily metrics уже есть как минимум для:

- `load_state_daily_v2`
- `readiness_daily`

Recovery layer пока документируется через текущее baseline behavior и explanation payload.
