# Readiness Model

## 1. Purpose

Этот документ описывает текущую readiness model в Human Engine.

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

### 3.1 Model V2 overview

```text
LoadState + RecoveryState -> Readiness -> GoodDayProbability
```

Где:

- `LoadState` materialized в `load_state_daily_v2`
- `RecoveryState` materialized в `health_recovery_daily`
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

### 3.4 Readiness inputs

Текущая readiness model v2 использует:

- `freshness` из `load_state_daily_v2`
- `recovery_score_simple` из `health_recovery_daily`

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

### 4.3 Baseline formula v2

Сначала `freshness` нормализуется:

```text
freshness_norm = clamp(50 + freshness, 0, 100)
```

Затем readiness считается так:

```text
readiness_score_raw = 0.6 * freshness_norm + 0.4 * recovery_score_simple
```

Fallback behavior:

- если есть и load, и recovery, используется полная формула `0.6 * freshness_norm + 0.4 * recovery_score_simple`
- если есть только recovery, используется `recovery_only` fallback и `readiness_score_raw = recovery_score_simple`
- если есть только load, используется `load_only` fallback и `readiness_score_raw = freshness_norm`
- если нет ни load, ни recovery, backend возвращает `404` и не создает row в `readiness_daily`

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

### 7.1 `readiness_daily.explanation_json`

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
- payload, который используется UI и Telegram notification layer

---

## 8. Telegram readiness briefing

Daily Telegram notification в текущем backend строится от `readiness_daily`, а не от legacy freshness-only summary.

Source of truth:

- `readiness_score`
- `good_day_probability`
- `status_text`
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
- использует recovery breakdown как основной источник интерпретации recovery contour
- может дополнительно учитывать сильно отрицательный freshness

---

## 9. Limitations

Текущая модель:

- использует агрегированный recovery score как вход readiness
- пока не подает `hrv_dev`, `rhr_dev` и component scores в readiness formula напрямую
- пока не имеет отдельной probability calibration
- требует дальнейшей верификации на реальных данных

---

## 10. Planned extensions

Планируется:

- калибровка весов `freshness_norm` и `recovery_score_simple`
- возможное явное использование `sleep_score`, `hrv_dev`, `rhr_dev` в readiness formula
- уточнение interpretation layer для `good_day_probability`
- уточнение decision mapping

Но:

- без потери прозрачности
- с явным versioning

---

## 11. Debugging model

Если результат кажется неверным, проверять:

1. входные данные HealthKit и training load
2. расчет `health_recovery_daily`
3. расчет `load_state_daily_v2`
4. нормализацию `freshness`
5. формирование `readiness_score_raw`
6. status mapping и probability mapping
7. `readiness_daily.explanation_json`
8. daily notification payload, если вопрос относится к Telegram briefing

---

## 12. Design constraint

Любое усложнение модели должно:

- улучшать объяснимость
- не нарушать deterministic поведение
- быть отделено от planned layers

Иначе его не нужно добавлять.

---

## 13. E2E readiness pipeline definition of done

Сценарий readiness считается завершенным для Model V2 baseline, когда:

- HealthKit full-sync пересчитывает `health_recovery_daily` для affected dates
- `load_state_daily_v2` дотягивается минимум до latest recovery date
- `readiness_daily` создается или обновляется для affected dates
- `readiness_daily.explanation_json` содержит `recovery_explanation`
- при доступном load-контуре `freshness` не является `null`
- API не падает на частично неполных данных и использует зафиксированные fallback-режимы
