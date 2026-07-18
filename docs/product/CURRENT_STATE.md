# Whatte — CURRENT STATE

Last updated: 2026-05-21

---

## 1. Общий статус

Whatte перешел от load-only readiness к рабочей baseline-архитектуре Model V2.

Текущая схема:

```text
LoadState + RecoveryState -> Readiness -> GoodDayProbability
```

Система уже работает как end-to-end pipeline:

```text
iOS -> public API -> backend -> raw -> normalized -> recovery -> readiness -> response
```

Это уже не только модельная заготовка. В backend реализованы ingestion, materialized daily layers и response path.

Daily Telegram readiness briefing также переведен на `readiness_daily` и recovery breakdown из `explanation_json`.

---

## 2. Архитектура (актуальная)

### 2.1 Load contour

Источник:

- Strava

Pipeline:

- `strava_activity_raw`
- `daily_training_load`
- `load_state_daily_v2`

Содержит:

- `tss`
- `load_input_nonlinear`
- `fitness`
- `fatigue_fast`
- `fatigue_slow`
- `fatigue_total`
- `freshness`
- `version`

### 2.2 Recovery contour

Источник:

- HealthKit

Pipeline:

- `healthkit_ingest_raw`
- normalized tables:
  - `health_sleep_night`
  - `health_resting_hr_daily`
  - `health_hrv_sample`
  - `health_weight_measurement`
- `health_recovery_daily`

Содержит:

- `sleep_minutes`
- `awake_minutes`
- `rem_minutes`
- `deep_minutes`
- `resting_hr_bpm`
- `hrv_daily_median_ms`
- `weight_kg`
- `recovery_score_simple`
- `recovery_explanation_json`

Важно:

- таблица `health_recovery_daily` уже реализована
- поле `recovery_score_simple` исторически сохраняет старое имя
- по смыслу текущий recovery layer уже baseline-aware, а не purely heuristic-only placeholder
- breakdown recovery baseline сохраняется в `recovery_explanation_json`

### 2.3 Readiness layer

Pipeline:

- `load_state_daily_v2 + health_recovery_daily -> readiness_daily`

Содержит:

- `freshness`
- `recovery_score_simple`
- `readiness_score_raw`
- `readiness_score`
- `good_day_probability`
- `status_text`
- `explanation_json`
- `version`

Важно:

- readiness хранится как отдельный daily storage layer
- readiness не равен `freshness`
- readiness объединяет load contour и recovery contour
- на последних health dates readiness считается из двух контуров, а не fallback-only от recovery
- `readiness_daily.explanation_json` теперь включает recovery breakdown из `health_recovery_daily.recovery_explanation_json`
- daily Telegram notification строится от `readiness_daily`, а не от legacy freshness-only summary

---

## 3. Data pipeline

### 3.1 HealthKit full sync

Endpoint:

`POST /api/v1/healthkit/full-sync/{user_id}`

Статус:

- full-sync теперь является self-sufficient orchestration endpoint
- current state после одного full-sync считается end-to-end на backend

Flow:

1. raw ingest в `healthkit_ingest_raw`
2. latest raw -> normalized health tables
3. сбор affected dates
4. recompute `health_recovery_daily`
5. recompute `load_state_daily_v2` минимум до max affected date
6. recompute `readiness_daily`
7. агрегированный response обратно в клиент

### 3.2 Load model v2 recompute

Endpoint:

`POST /api/v1/model/load-state-v2/{user_id}`

Особенности:

- непрерывная календарная ось
- `load_state_daily_v2` строится до latest health/recovery date
- `tss = 0` в дни без тренировок
- fast + slow fatigue
- `fatigue_total` как weighted mixture

### 3.3 Readiness recompute

Endpoint:

`POST /api/v1/model/readiness-daily/{user_id}/{date}`

---

## 4. Реализованная baseline model

### 4.1 Load model v2

Параметры:

- `tau_fitness = 40`
- `tau_fatigue_fast = 4`
- `tau_fatigue_slow = 9`
- `weight_fatigue_fast = 0.65`
- `weight_fatigue_slow = 0.35`

Расчеты:

```text
load_input_nonlinear = TSS
fatigue_total = 0.65 * fatigue_fast + 0.35 * fatigue_slow
freshness = fitness - fatigue_total
```

Важно:

- поле называется `load_input_nonlinear`
- в текущем backend это все еще линейный input по TSS

### 4.2 Recovery baseline

Текущий recovery scoring:

- использует `sleep_minutes`
- использует `hrv_today` и `rhr_today`
- использует `hrv_baseline` и `rhr_baseline`
- считает `hrv_dev` и `rhr_dev`
- считает `sleep_score`, `hrv_score`, `rhr_score`
- сохраняет breakdown в `recovery_explanation_json`

Базовая формула:

```text
recovery_score_simple = 0.4 * hrv_score + 0.3 * rhr_score + 0.3 * sleep_score
```

Если baseline для компонента недоступен, используется нейтральное значение.

### 4.3 Readiness baseline

Текущая формула:

```text
freshness_norm = clamp(50 + freshness, 0, 100)
readiness_score_raw = 0.6 * freshness_norm + 0.4 * recovery_score_simple
readiness_score = clamp(round(readiness_score_raw, 1), 0, 100)
good_day_probability = readiness_score / 100
```

Важно:

- `good_day_probability` уже реализован
- это baseline probability-like mapping
- это не статистически откалиброванная вероятность
- readiness formula не менялась; расширен только explanation payload

---

## 5. Что уже работает end-to-end

- iOS приложение отправляет HealthKit payload
- backend принимает `full-sync` как self-sufficient orchestration endpoint
- данные попадают в raw таблицу
- latest raw раскладывается в normalized health tables
- пересчитывается `health_recovery_daily`
- `load_state_daily_v2` дотягивается до latest health/recovery date
- на последних датах `readiness_daily` считается из load contour + recovery contour
- `readiness_daily.explanation_json` содержит recovery breakdown
- результат возвращается в iOS через public API

Публичный API уже проксируется через VPS / Caddy через `api.shchukin.de`.

Новый domain split:

- `shchukin.de` — web surfaces
- `shchukin.de/dashboard` — Internal Dashboard
- `api.shchukin.de` — technical API, Strava OAuth callback, Telegram webhook, HealthKit sync, `/healthz`, OpenAPI/docs when enabled

Dashboard status:

- dashboard implemented as FastAPI SSR HTML with Jinja2 and minimal CSS
- dashboard is protected at the edge with `Caddy` Basic Auth
- current sections:
  - `System`: backend status, database status, server time, process started time, uptime, and safe database error fallback
  - `Connection`: Strava connection status, athlete id, scope, token expiry, and token state
  - `Ingest Jobs`: latest ingest jobs plus pending and failed/error counts
  - `Strava Activities`: latest saved local activities with total count, name/type/date/distance/time
- dashboard is read-only and uses local backend/database state only
- dashboard does not call Strava API, refresh tokens, mutate DB rows, show raw payloads, or expose secrets
- token refresh remains limited to Strava API access paths, not dashboard reads

Operational monitoring status:

- dashboard is the primary operational monitoring surface for the current VPS production backend
- Telegram alerts and the old home-server watchdog / cron monitoring are legacy/secondary, not the main monitoring channel
- dashboard is not a full alerting system

---

## 6. Decision, delivery and feedback layers

### 6.1 Deterministic decision baseline

Поверх `readiness_daily` уже работает baseline decision layer:

- `recommendation`
- `reason`
- `briefing`

Текущий mapping:

- `< 40` -> `recovery`
- `40 <= score < 60` -> `endurance`
- `60 <= score <= 75` -> `moderate`
- `> 75` -> `high_intensity`

Важно:

- decision layer не меняет readiness formula
- decision layer не использует AI / LLM
- это baseline guidance, а не полноценный planner по времени, длительности и контексту дня

### 6.2 Delivery layer

Уже реализованы:

- GET readiness API с `recommendation`, `reason`, `briefing`, `data_quality`
- daily Telegram readiness delivery
- deterministic formatting для iOS / Today-style consumption

### 6.3 Subjective feedback layer

Уже реализованы:

- post-ride RPE prompt
- next-day recovery prompt
- `activity_subjective_feedback`
- `subjective_feedback_prompt_log`

Важно:

- feedback не меняет deterministic core calculations
- feedback сохраняется как evaluation / calibration dataset

## 7. Основные ограничения текущей версии

1. Recovery baseline уже реализован, но еще не откалиброван на популяционных или персональных outcome данных.
2. `load_input_nonlinear` пока фактически линейный.
3. `good_day_probability` пока является простым mapping от readiness score.
4. Decision layer уже реализован, но пока остается узким baseline mapping без time-aware planning и duration guidance.
5. В notification / briefing flows сохраняется риск архитектурного дрейфа: часть legacy formatting logic еще живет вне `decision_engine`, что может со временем разъехать тексты и правила.
6. Персонализация и calibration остаются следующим этапом.

## 8. Ключевые архитектурные решения

- Load и Recovery разделены
- Readiness не равен freshness
- Readiness хранится отдельно в `readiness_daily`
- Recovery влияет на readiness, но не переписывает load model
- используется daily aggregation
- используется probability layer (`good_day_probability`)
- baseline decision layer отделен от readiness formula
- subjective feedback хранится отдельно от model state как calibration dataset
- deterministic core остается приоритетом

---

## 8. Текущие источники данных

### Реальные

- Strava
- HealthKit

### Planned

- Garmin
- дополнительные recovery signals
- decision / recommendation outputs

---

## 9. Следующие шаги (приоритет)

### P1 — Calibration

- readiness / probability calibration
- проверка recovery baseline на реальных данных
- уточнение readiness zones

### P2 — Decision layer

- recommendation layer поверх readiness
- rule-based decision mapping

### P3 — UX / Product integration

- user-facing readiness screen в iOS
- объяснения на основе уже существующих breakdown payloads

### P4 — Model improvements

- nonlinear load transform
- personalization
- расширение feature layer

---

## 10. Definition of Done для текущей стадии

Система считается рабочей на текущем этапе, если:

- данные приходят из HealthKit и Strava
- считается `load_state_daily_v2`
- считается `health_recovery_daily`
- считается `readiness_daily`
- `good_day_probability` доступен как отдельный output
- документация соответствует реальному backend baseline
