# Whatte — Current Metrics Methodology

**Version:** v2 baseline  
**Status:** active baseline  
**Last updated:** 2026-04-09

# Whatte — методика расчета текущих метрик

## Назначение

Этот документ описывает, как в текущей backend-реализации Whatte рассчитываются основные метрики тренировки и состояния.

Документ фиксирует **реально реализованный baseline для Model V2**. Если код меняется, методика должна обновляться вместе с ним.

## Область действия

Сейчас в Whatte используются две группы метрик:

1. Метрики тренировки
   - длительность
   - средняя мощность
   - нормализованная мощность
   - IF
   - TSS

2. Метрики состояния
   - Fitness
   - Fatigue Fast
   - Fatigue Slow
   - Fatigue Total
   - Freshness
   - Recovery Score Simple
   - Readiness
   - Good Day Probability
   - текстовый статус

---

## 1. Входные данные

Для тренировочных метрик используются данные активности и агрегированной нагрузки.

Для recovery- и readiness-метрик используются:

- `daily_training_load`
- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

### Принцип выбора FTP

Для внутренних расчетов Whatte используется текущее значение FTP, принятое внутри системы.

Если в источнике и в Whatte заданы разные значения FTP, то `IF` и `TSS` будут системно различаться.

---

## 2. Метрики тренировки

### 2.1 Длительность

Длительность тренировки хранится в секундах:

```text
duration_sec = длительность в секундах
duration_hr = duration_sec / 3600
```

---

### 2.2 Средняя мощность

```text
Avg Power = mean(power_t)
```

Если источник уже отдает агрегированную метрику, система может использовать ее напрямую.

---

### 2.3 Нормализованная мощность

Целевой принцип:

```text
NP = ( mean( rolling30_power^4 ) )^(1/4)
```

Но итог зависит от доступных данных:

- если есть сырой ряд мощности, расчет должен идти по нему
- если есть только агрегированное значение источника, временно может использоваться оно

---

### 2.4 Intensity Factor

```text
IF = NP / FTP
```

---

### 2.5 TSS

Эквивалентные формы:

```text
TSS = duration_hr * IF^2 * 100
```

или

```text
TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100
```

---

## 3. Метрики состояния

Текущие метрики состояния опираются на двухконтурную модель:

- load contour
- recovery contour

Их объединение формирует readiness layer.

---

### 3.1 Load model v2

`load_state_daily_v2` рассчитывается по непрерывной календарной оси.

Это означает:

- используются все даты в диапазоне
- в дни без тренировок подставляется `tss = 0`

#### 3.1.1 Load input

Поле называется `load_input_nonlinear`, но в текущем backend baseline:

```text
load_input_nonlinear = TSS
```

То есть вход сейчас линейный.

#### 3.1.2 Fitness

```text
Fitness_new = Fitness_prev + (load_input - Fitness_prev) / 40
```

#### 3.1.3 Fatigue Fast

```text
FatigueFast_new = FatigueFast_prev + (load_input - FatigueFast_prev) / 4
```

#### 3.1.4 Fatigue Slow

```text
FatigueSlow_new = FatigueSlow_prev + (load_input - FatigueSlow_prev) / 9
```

#### 3.1.5 Fatigue Total

В текущей Model V2:

```text
FatigueTotal = 0.65 * FatigueFast + 0.35 * FatigueSlow
```

Это важно: в backend это **взвешенная смесь**, а не простая сумма.

#### 3.1.6 Freshness

```text
Freshness = Fitness - FatigueTotal
```

`Freshness` описывает load contour, но не равен readiness.

---

### 3.2 Recovery layer

`health_recovery_daily` агрегируется из:

- sleep
- resting HR
- HRV
- latest known weight

Текущие поля:

- `sleep_minutes`
- `awake_minutes`
- `rem_minutes`
- `deep_minutes`
- `resting_hr_bpm`
- `hrv_daily_median_ms`
- `weight_kg`
- `recovery_score_simple`
- `recovery_explanation_json`

#### 3.2.1 Recovery Score Simple

`recovery_score_simple` остается именем поля, но текущий backend baseline уже использует baseline-aware scoring `0..100`.

Свойства:

- строится из сна, resting HR и HRV
- использует baseline HRV и baseline resting HR, если они доступны
- сохраняет breakdown в `recovery_explanation_json`
- является baseline-слоем, а не финальной откалиброванной recovery model

#### 3.2.2 Recovery baseline components

Текущий recovery scoring использует:

- `hrv_baseline`
- `rhr_baseline`
- `hrv_dev`
- `rhr_dev`
- `sleep_score`
- `hrv_score`
- `rhr_score`

Базовая формула:

```text
sleep_score = clamp(min(sleep_minutes / 480, 1.0) * 100, 0, 100)
hrv_score = clamp(50 + 50 * hrv_dev, 0, 100)
rhr_score = clamp(50 - 50 * rhr_dev, 0, 100)
recovery_score_simple = 0.4 * hrv_score + 0.3 * rhr_score + 0.3 * sleep_score
```

Если baseline недоступен для компонента, используется нейтральное значение `50`.

---

### 3.3 Readiness

`Readiness` — отдельный прикладной слой, который объединяет load contour и recovery contour.

#### 3.3.1 Freshness normalization

Перед объединением:

```text
freshness_norm = clamp(50 + Freshness, 0, 100)
```

#### 3.3.2 Baseline formula

```text
Readiness_raw = 0.6 * Freshness_norm + 0.4 * RecoveryScoreSimple
```

Fallback behavior:

- если нет recovery score, используется `Freshness_norm`
- если нет load score, используется `RecoveryScoreSimple`

`readiness_daily.explanation_json` при этом хранит:

- `freshness`
- `freshness_norm`
- `recovery_score_simple`
- `weights`
- `formula`
- `recovery_explanation`

Где `recovery_explanation` прокидывается из `health_recovery_daily.recovery_explanation_json`, чтобы readiness layer содержал не только итоговый recovery score, но и recovery breakdown.

#### 3.3.3 Final readiness score

```text
Readiness = clamp(round(Readiness_raw, 1), 0, 100)
```

#### 3.3.4 Good Day Probability

Текущая backend-реализация:

```text
GoodDayProbability = Readiness / 100
```

Это baseline probability-like mapping, а не откалиброванная статистическая вероятность.

#### 3.3.5 Текстовый статус

Текущий status mapping:

- `0..24` -> `Высокая усталость`
- `25..44` -> `Нагрузка`
- `45..64` -> `Нормальная готовность`
- `65..84` -> `Хорошая готовность`
- `85..100` -> `Очень свежий`

---

## 4. Что важно понимать про текущую модель

### Это рабочий baseline

Текущая схема нужна как проверяемый и воспроизводимый слой. Она:

- проста для проверки
- понятна математически
- уже реализована в backend
- отделяет load и recovery

### Что уже реализовано

- HealthKit ingestion
- normalized health tables
- `health_recovery_daily`
- `recovery_explanation_json`
- `load_state_daily_v2`
- `readiness_daily`
- `good_day_probability`

### Ограничения текущего подхода

1. `load_input_nonlinear` пока фактически линейный.
2. Recovery-контур уже baseline-aware, но readiness formula пока использует его как агрегированный score, а не как full multicomponent formula.
3. `GoodDayProbability` пока является простым mapping от readiness score.
4. Decision layer поверх readiness еще не откалиброван окончательно.
