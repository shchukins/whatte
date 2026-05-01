# Human Engine — Model V2 Architecture

## Контекст

Model V2 уже реализована в backend как baseline-архитектура.

Переход выполнен от load-only readiness к двухконтурной схеме:

```text
LoadState + RecoveryState -> Readiness -> GoodDayProbability
```

Это означает:

- readiness больше не равен freshness
- recovery является отдельным контуром
- readiness хранится как отдельный слой `readiness_daily`

---

# 1. Архитектурные принципы

## 1.1 Load и Recovery — независимые контуры

Load:

- отражает тренировочную нагрузку
- формируется из `daily_training_load`
- материализуется в `load_state_daily_v2`

Recovery:

- отражает восстановление организма
- формируется из HealthKit-derived tables
- материализуется в `health_recovery_daily`

Важно:

Recovery не заменяет fatigue, а корректирует итоговую readiness поверх load model.

---

## 1.2 Readiness ≠ Freshness

В legacy load-only подходе readiness мог использоваться как proxy от freshness.

В текущей Model V2:

```text
readiness = f(load_state, recovery_state)
```

---

## 1.3 Fast / Slow fatigue

В Model V2 используются:

- `fatigue_fast`
- `fatigue_slow`
- `fatigue_total`

Где:

```text
fatigue_total = 0.65 * fatigue_fast + 0.35 * fatigue_slow
freshness = fitness - fatigue_total
```

---

## 1.4 Calendar-continuous load state

`load_state_daily_v2` считается по непрерывной календарной оси.

Это означает:

- расчет идет не только по тренировочным дням
- в дни без тренировок используется `tss = 0`

---

## 1.5 Current load input

Поле называется `load_input_nonlinear`, но текущий backend baseline использует линейный input:

```text
load_input_nonlinear = TSS
```

Нелинейная трансформация пока не реализована.

---

## 1.6 Probability layer

Model V2 вводит:

- `readiness_score`
- `good_day_probability`

Текущий baseline:

```text
good_day_probability = readiness_score / 100
```

Это probability-like layer для decision support, а не финально откалиброванная вероятность.

---

# 2. Архитектура слоев

## 2.1 Ingestion layer

Источники:

- Strava
- HealthKit

Реализовано:

- Strava ingestion baseline
- HealthKit raw ingest
- HealthKit full-sync orchestration

---

## 2.2 Raw layer

Ключевые raw сущности:

- `strava_activity_raw`
- `healthkit_ingest_raw`

---

## 2.3 Normalized layer

Текущие normalized health tables:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

Load-side daily aggregate:

- `daily_training_load`

---

## 2.4 Recovery layer

Текущая таблица:

- `health_recovery_daily`

Содержит:

- sleep metrics
- resting HR
- HRV daily median
- latest weight
- `recovery_score_simple`
- `recovery_explanation_json`

Текущий recovery baseline:

- использует `hrv_baseline` и `rhr_baseline`
- считает `hrv_dev` и `rhr_dev`
- считает component scores для sleep, HRV и resting HR
- сохраняет breakdown в explanation payload

---

## 2.5 Load model layer

Текущая таблица:

- `load_state_daily_v2`

Содержит:

- `tss`
- `load_input_nonlinear`
- `fitness`
- `fatigue_fast`
- `fatigue_slow`
- `fatigue_total`
- `freshness`

---

## 2.6 Readiness layer

Текущая таблица:

- `readiness_daily`

Содержит:

- `freshness`
- `recovery_score_simple`
- `readiness_score_raw`
- `readiness_score`
- `good_day_probability`
- `status_text`
- `explanation_json`

---

# 3. HealthKit full-sync architecture

Текущий iOS sync endpoint:

```text
POST /api/v1/healthkit/full-sync/{user_id}
```

Pipeline:

```text
raw ingest
-> latest raw -> normalized
-> recompute health_recovery_daily
-> recompute load_state_daily_v2
-> recompute readiness_daily
```

Фактический orchestration contract:

- сначала пересчитывается `health_recovery_daily` для affected dates
- затем `load_state_daily_v2` пересчитывается до latest recovery date
- затем `readiness_daily` создается или обновляется для affected dates
- pipeline валидирует, что `readiness_daily.explanation_json` содержит `recovery_explanation`
- pipeline валидирует, что при доступном load-контуре `freshness` не равен `null`

---

# 4. Load Model V2

## 4.1 Параметры

- `tau_fitness = 40`
- `tau_fatigue_fast = 4`
- `tau_fatigue_slow = 9`
- `weight_fatigue_fast = 0.65`
- `weight_fatigue_slow = 0.35`

## 4.2 Формулы

```text
fitness[d] =
    fitness[d-1] + (load_input[d] - fitness[d-1]) / 40

fatigue_fast[d] =
    fatigue_fast[d-1] + (load_input[d] - fatigue_fast[d-1]) / 4

fatigue_slow[d] =
    fatigue_slow[d-1] + (load_input[d] - fatigue_slow[d-1]) / 9

fatigue_total[d] =
    0.65 * fatigue_fast[d] + 0.35 * fatigue_slow[d]

freshness[d] =
    fitness[d] - fatigue_total[d]
```

---

# 5. Recovery Model

Источник: HealthKit.

Текущая реализация:

- raw payload сохраняется
- latest raw раскладывается в normalized tables
- `health_recovery_daily` агрегирует day-level recovery state

Текущий recovery output:

- `recovery_score_simple`
- `recovery_explanation_json`

Это baseline-aware recovery score, не финальная откалиброванная recovery model.

---

# 6. Readiness Model V2

## 6.1 Baseline formula

```text
freshness_norm = clamp(50 + freshness, 0, 100)
readiness_score_raw = 0.6 * freshness_norm + 0.4 * recovery_score_simple
readiness_score = clamp(round(readiness_score_raw, 1), 0, 100)
good_day_probability = readiness_score / 100
```

## 6.2 Fallback behavior

Readiness baseline не меняет формулу, но фиксирует controlled fallbacks:

- full path: `LoadState + RecoveryState`
  - `readiness_score_raw = 0.6 * freshness_norm + 0.4 * recovery_score_simple`
  - `fallback_mode = null`
- recovery-only:
  - `readiness_score_raw = recovery_score_simple`
  - `fallback_mode = "recovery_only"`
- load-only:
  - `readiness_score_raw = freshness_norm`
  - `fallback_mode = "load_only"`
- no-data:
  - backend возвращает `404`
  - `readiness_daily` row не создается

Во всех сценариях `good_day_probability = readiness_score / 100`.

## 6.3 Storage

Readiness хранится отдельно в `readiness_daily`.

Это важно архитектурно:

- readiness не является просто полем load state
- readiness — отдельный daily layer поверх двух контуров

---

# 7. Product-level consequence

Текущая продуктовая схема:

```text
LoadState + RecoveryState -> Readiness -> GoodDayProbability
```

Это и есть текущий baseline Human Engine.

---

# 8. Planned next steps

- калибровка readiness / probability
- расширение recovery signals
- уточнение decision mapping
- синхронизация recommendation / ride briefing с readiness layer

---

# 9. Что сознательно не делаем сейчас

- ML-модели в core
- black-box probability layer
- скрытую интерпретацию readiness
- LLM-based decision logic

Причина:

приоритет — прозрачность, воспроизводимость и инженерная проверяемость.
