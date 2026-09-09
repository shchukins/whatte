# Readiness Model

## 1. Purpose

Этот документ описывает текущую readiness model в Whatte.

Цель:

- определить, насколько спортсмен готов к нагрузке
- зафиксировать текущую baseline-логику backend
- сделать модель прозрачной и объяснимой

---

## 2. Principles

Модель должна быть:

- deterministic
- простой
- объяснимой
- воспроизводимой

Нельзя:

- использовать скрытую логику
- использовать LLM
- подменять readiness только load-only proxy

---

## 3. State model

### 3.1 Current signal-composition overview

```text
load + freshness + response + feeling + optional physiology
-> Readiness -> GoodDayProbability
```

Где:

- `LoadState` materialized в `load_state_daily_v2`
- `RecoveryState` materialized в `health_recovery_daily`
- morning `feeling` хранится в `activity_subjective_feedback`
- `Readiness` materialized в `readiness_daily`
- `GoodDayProbability` хранится как отдельный output внутри `readiness_daily`

### 3.2 LoadState

Текущий `LoadState` использует:

- `freshness` из `load_state_daily_v2`

Важно:

- readiness больше не равен freshness
- recovery contour не заменяет load contour, а дополняет его

`LoadState` включает:

- `fitness`
- `fatigue_fast`
- `fatigue_slow`
- `freshness`

Дополнительно внутри materialized load layer также присутствует:

- `fatigue_total`
- `tss`
- `load_input_nonlinear`

### 3.3 RecoveryState

Текущий `RecoveryState` использует:

- `recovery_score_simple` из `health_recovery_daily`
- `recovery_explanation_json`

Дополнительные recovery-компоненты уже считаются внутри recovery layer, но пока не входят в readiness formula напрямую как отдельные веса:

- `sleep_score`
- `hrv_score`
- `rhr_score`
- `hrv_dev`
- `rhr_dev`
- baseline values:
  - `hrv_baseline`
  - `rhr_baseline`

### 3.4 Readiness signal families

Текущая версия `v2_signal_composition_response_v1` публикует пять стабильных
семейств:

- `load` — доступный контекст load state; отдельно не взвешивается, чтобы не
  учитывать одну нагрузку дважды
- `freshness` — readiness-bearing summary load state
- `response` — latest versioned activity-response context за семь дней;
  baseline deviations участвуют в readiness, когда пригоден хотя бы один
  component
- `feeling` — утренняя субъективная recovery-оценка 1-5
- `physiology` — optional `recovery_score_simple` из `health_recovery_daily`

---

## 4. Core logic

Основная идея:

> readiness определяется сочетанием load state и recovery state

### 4.1 Load contour

Load contour формируется в `load_state_daily_v2`:

- `fitness`
- `fatigue_fast`
- `fatigue_slow`
- `fatigue_total`
- `freshness`

Где:

- `fatigue_total = 0.65 * fatigue_fast + 0.35 * fatigue_slow`
- `freshness = fitness - fatigue_total`

Важно:

- календарная ось непрерывная
- `load_state_daily_v2` строится до latest relevant date
- если после последней тренировки есть recovery dates, для них сохраняется `tss = 0`
- freshness на этих датах продолжает считаться через естественное затухание fatigue

### 4.2 Recovery contour

Recovery contour формируется в `health_recovery_daily` из:

- сна
- HRV
- resting HR
- веса

Текущий прикладной выход этого слоя:

- `recovery_score_simple`
- `recovery_explanation_json`

Важно:

- имя `recovery_score_simple` сохранено для совместимости схемы и API
- по факту текущий backend baseline уже использует baseline-aware scoring

### 4.3 Signal composition formula

Сначала `freshness` нормализуется:

```text
freshness_norm = clamp(50 + freshness, 0, 100)
```

`freshness` имеет configured weight `0.6`. `response` получает максимум `0.2`
из evidence budget `0.4`; остаток делят доступные `feeling` и `physiology`.
Недоступные scored-сигналы исключаются, после чего доступные веса нормализуются
до `1.0`.

```text
feeling_norm = (feeling_score - 1) * 25
response_recency = clamp(1 - max(age_days - 1, 0) / 6, 0, 1)
response_configured_weight = 0.2 * response_recency
readiness_score_raw = sum(available_signal_score * normalized_effective_weight)
```

Response score нормализует comparable-session deviations:

```text
efficiency_score = clamp(50 + 2 * power_hr_deviation_pct, 0, 100)
subjective_cost_score = clamp(50 - 2 * rpe_cost_deviation_pct, 0, 100)
drift_score = clamp(50 - 10 * drift_delta_percentage_points, 0, 100)
```

Objective score сначала усредняет доступные efficiency/drift components.
Итоговый response score затем усредняет доступные objective и subjective
channels. Для subjective cost выбирается `session_rpe_load_per_tss`, а
`rpe_per_intensity_factor` служит fallback; вместе они не учитываются.

Raw RPE, session-RPE load, TSS, duration, absolute power и absolute HR не входят
в readiness напрямую. `load` по-прежнему имеет weight `0`; load state влияет
только через `freshness`.

Основные комбинации:

- freshness only: `1.0 * freshness_norm`
- freshness + physiology: `0.6 * freshness_norm + 0.4 * physiology`
- freshness + feeling: `0.6 * freshness_norm + 0.4 * feeling`
- freshness + feeling + physiology: `0.6 * freshness_norm + 0.2 * feeling + 0.2 * physiology`
- freshness + fresh response + feeling + physiology:
  `0.6 * freshness_norm + 0.2 * response + 0.1 * feeling + 0.1 * physiology`
- freshness + fresh response: configured `0.6 / 0.2`, effective `0.75 / 0.25`
- если нет ни одного scored-сигнала, backend возвращает `404`

Missing physiology имеет state `unavailable`, contribution `0` и никогда не
интерпретируется как плохое recovery. Полное обоснование composition зафиксировано в
`backend/backend/services/readiness_composition.py`.

### 4.4 Final outputs

```text
readiness_score = clamp(round(readiness_score_raw, 1), 0, 100)
good_day_probability = readiness_score / 100
```

`good_day_probability` пока является baseline probability-like mapping, а не откалиброванной статистической вероятностью.

`Readiness` слой хранит:

- `readiness_score`
- `good_day_probability`
- `status_text`
- `explanation_json`

Новые вычисления сохраняются с
`version = 'v2_signal_composition_response_v1'`. Rows версий `v2` и
`v2_signal_composition` не перезаписываются.

---

## 5. Status zones

Текущие статусные зоны backend:

### 5.1 Высокая усталость

- `readiness_score <= 24`

### 5.2 Нагрузка

- `25 <= readiness_score <= 44`

### 5.3 Нормальная готовность

- `45 <= readiness_score <= 64`

### 5.4 Хорошая готовность

- `65 <= readiness_score <= 84`

### 5.5 Очень свежий

- `readiness_score >= 85`

---

## 6. Output

Результат текущей модели:

- `readiness_score_raw`
- `readiness_score`
- `good_day_probability`
- `status_text`
- `explanation_json`

`readiness_daily` является отдельным storage layer для этих outputs.

Readiness считается ежедневно и сохраняется в `readiness_daily`.

Основной backend response / query layer для readiness опирается на:

- `readiness_daily.readiness_score`
- `readiness_daily.good_day_probability`
- `readiness_daily.status_text`
- `readiness_daily.explanation_json`

---

## 7. Explanation payload

### 7.0 Fallback modes

Текущий backend фиксирует четыре режима:

- full:
  - есть `LoadState` и `RecoveryState`
  - используется формула `0.6 * freshness_norm + 0.4 * recovery_score_simple`
  - `fallback_mode = null`
- `recovery_only`:
  - есть только `RecoveryState`
  - `readiness_score_raw = recovery_score_simple`
- `load_only`:
  - есть только `LoadState`
  - `readiness_score_raw = freshness_norm`
- `no_data`:
  - нет ни load, ни recovery
  - backend возвращает `404`
  - row в `readiness_daily` не создается

Текущий `explanation_json` хранит:

- `fallback_mode`
- `freshness`
- `freshness_norm`
- `recovery_score_simple`
- `recovery_explanation`
- `weights`
- `formula`
- `source_timestamps`

Где:

- `recovery_explanation` протягивается из `health_recovery_daily.recovery_explanation_json`
- readiness formula при этом не меняется

Внутри `recovery_explanation` текущий backend хранит breakdown recovery state:

- `sleep_score`
- `hrv_score`
- `rhr_score`
- `hrv_baseline`
- `rhr_baseline`
- `hrv_dev`
- `rhr_dev`

Это нужно для explainability и отладки.

### 7.1 Readiness source-data freshness

Readiness source-data freshness is a separate deterministic query contract. It
must not be confused with the load-model field `freshness`.

At recomputation time, `explanation_json.source_timestamps` snapshots:

- `recovery_source_at`: the `health_recovery_daily.date` row used, or `null`;
- `training_source_at`: the `load_state_daily_v2.date` row used, or `null`;
- `timezone`: the explicit `WHATTE_TIMEZONE` configuration.

The readiness formula, weights, fallback modes, score zones, recommendation
thresholds, and `good_day_probability` are unchanged. Source freshness only
classifies whether the saved evidence is current:

- exact target-day evidence is current;
- older source evidence is stale;
- supported one-family fallback plus a current available family is partial;
- absent/invalid required evidence is missing.

`data_quality` continues to describe input completeness. Source freshness
describes currency. Model confidence is a third, separate concern and is not
inferred from either field.

### 7.2 Missing recovery inputs

Historical recovery replay обрабатывает частично неполные HealthKit данные до readiness:

- если нет HRV за день или baseline HRV, `hrv_score = 50.0`
- если нет resting HR за день или baseline resting HR, `rhr_score = 50.0`
- если нет sleep, `sleep_score = 50.0`
- если нет вообще health data, recovery recompute возвращает `404`

Production collection retired. Readiness не меняет historical recovery logic и
получает уже рассчитанный exact-date `recovery_score_simple`, когда row существует.

### 7.3 `readiness_daily.explanation_json`

Структура текущего explanation payload:

```json
{
  "fallback_mode": null,
  "formula": "0.6 * freshness_norm + 0.4 * recovery_score_simple",
  "weights": {
    "freshness_norm": 0.6,
    "recovery_score_simple": 0.4
  },
  "freshness": 5.0,
  "freshness_norm": 55.0,
  "recovery_score_simple": 56.5,
  "source_timestamps": {
    "recovery_source_at": "2026-05-02",
    "training_source_at": "2026-05-02",
    "timezone": "Europe/Moscow"
  },
  "recovery_explanation": {
    "sleep_score": 82.8,
    "hrv_score": 42.1,
    "rhr_score": 49.5,
    "hrv_baseline": 61.0,
    "rhr_baseline": 52.0,
    "hrv_dev": -0.12,
    "rhr_dev": 0.03
  }
}
```

Для fallback-сценариев contract фиксирован так:

- `recovery_only`:
  - `fallback_mode = "recovery_only"`
  - `freshness = null`
  - `freshness_norm = null`
  - `recovery_score_simple` сохраняется
  - `good_day_probability = readiness_score / 100`
- `load_only`:
  - `fallback_mode = "load_only"`
  - `freshness` и `freshness_norm` сохраняются
  - `recovery_score_simple = null`
  - `good_day_probability = readiness_score / 100`
- full formula path:
  - `fallback_mode = null`
  - `recovery_explanation` протягивается из `health_recovery_daily.recovery_explanation_json`
- `no_data`:
  - backend возвращает `404`
  - readiness не пересчитывается и row не создается

Это:

- explainability слой
- способ показать breakdown readiness без изменения самой readiness formula

### 7.3 Input data quality indicators

Readiness GET endpoints additionally expose a read-only `data_quality` block derived from the already stored `readiness_daily.explanation_json`.

Current response shape:

```json
{
  "data_quality": {
    "sleep": "ok",
    "hrv": "ok",
    "resting_hr": "ok",
    "training": "ok"
  }
}
```

Derivation rules in MVP:

- `sleep = "ok"` if `explanation_json.recovery_explanation.sleep_minutes` is not `null`, else `"missing"`
- `hrv = "ok"` if `explanation_json.recovery_explanation.hrv_today` is not `null`, else `"missing"`
- `resting_hr = "ok"` if `explanation_json.recovery_explanation.rhr_today` is not `null`, else `"missing"`
- `training = "missing"` if `explanation_json.freshness_norm` is `null` or `fallback_mode = "recovery_only"`
- `training = "ok"` otherwise

Important constraints:

- this is not a confidence score
- readiness formula does not change
- no health-condition inference is added
- `training = "partial"` is reserved for future explicit unsupported / continuity-only load detection
- payload, который используется UI и Telegram notification layer

Source-data freshness is a separate API contract. Each current computation
snapshots its recovery and training source dates plus `WHATTE_TIMEZONE` in
`explanation_json.source_timestamps`; read endpoints expose
`freshness_state` and `freshness_reason_codes`. It must not be confused with
the physiological load metric `freshness` or with `data_quality`.

---

## 8. Telegram readiness briefing

Daily Telegram notification в текущем backend строится от `readiness_daily`, а не от legacy freshness-only summary.

Delivery не меняет readiness formula. Scheduled worker сначала материализует
daily state за configured local date, затем отправляет briefing.

Notification metadata классифицирует optional physiology input:

- `fresh`: historical `health_recovery_daily.date` точно соответствует дате briefing
- `missing`: physiology row отсутствует; это штатный optional state

Более старый historical recovery никогда не переносится на текущий день.

Freshness выводится в пользовательском сообщении, а один atomic daily claim в
`notification_log` предотвращает повторную отправку. Это delivery metadata; оно
не сохраняется в `readiness_daily` и не влияет на score, probability или
recommendation.

Source of truth:

- `readiness_score`
- `good_day_probability`
- `status_text`
- `recommendation`
- deterministic readiness briefing
- `explanation_json.freshness`
- `explanation_json.recovery_score_simple`
- `explanation_json.recovery_explanation`

В daily briefing выводятся:

- readiness score
- status text
- good day probability
- freshness
- recovery score
- recovery breakdown:
  - sleep score
  - HRV score
  - resting HR score

Комментарий:

- rule-based
- короткий и explainable
- использует deterministic briefing из decision layer
- не использует LLM

---

## 8.5 Relationship with subjective feedback

`readiness_daily` remains a deterministic derived-state layer.

`activity_subjective_feedback` остается отдельным persisted feedback layer.

The intended comparison is:

- readiness / recommendation at time `t`
- subjective outcome reported by the athlete at time `t` or `t+1 day`

This separation matters because:

- readiness is a model output
- subjective feedback is an observed outcome
- calibration requires comparing prediction and outcome without rewriting either layer

Current state:

- date-level `next_day_recovery` участвует как explicit `feeling` signal в
  `v2_signal_composition_response_v1`; исходный context snapshot сохраняет
  состояние до ответа
- post-ride RPE участвует только через baseline-relative response ratios; raw
  RPE не является readiness score
- feedback не запускает скрытую адаптацию весов или thresholds
- `good_day_probability` still has no statistical calibration
- the feedback dataset is being accumulated for future validation and calibration work

---

## 9. Limitations

Текущая модель:

- использует агрегированный recovery score как вход readiness
- пока не подает `hrv_dev`, `rhr_dev` и component scores в readiness formula напрямую
- пока не имеет отдельной probability calibration against accumulated subjective feedback
- не пересчитывает decision внутри history endpoint

---

## 10. Debugging model

Если результат кажется неверным, проверять:

1. training load, response и feeling inputs
2. exact-date historical physiology availability, если она ожидается
3. расчет `load_state_daily_v2`
4. нормализацию `freshness`
5. формирование `readiness_score_raw`
6. status mapping и probability mapping
7. `readiness_daily.explanation_json`
8. decision layer output, если вопрос относится к `recommendation` или `briefing`

---

## 11. Design constraint

Любое усложнение модели должно:

- улучшать объяснимость
- не нарушать deterministic поведение
- быть отделено от ingestion, recovery, load, readiness and decision boundaries

Иначе его не нужно добавлять.

---

## 12. E2E readiness pipeline definition of done

Сценарий readiness считается завершенным для Model V2 baseline, когда:

- `load_state_daily_v2` дотягивается до явной target date без physiology rows
- `readiness_daily` создается или обновляется для target date
- missing physiology публикуется как `unavailable`, а не как отрицательный signal
- exact-date historical physiology продолжает обогащать соответствующую дату
- при доступном load-контуре `freshness` не является `null`
- API не падает на частично неполных данных и использует зафиксированные fallback-режимы
