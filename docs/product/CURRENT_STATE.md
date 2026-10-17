# Whatte — CURRENT STATE

Last updated: 2026-10-17 (Europe/Moscow)

Сверка: `main` / `9013921a0e2a53e2b694114ed74ee8a53fb3966f`, код,
контракты, тесты и актуальные GitHub issues. `Implemented` ниже означает
реализацию в репозитории; это не самостоятельное доказательство production.
В этом обзоре production и персональные данные не читались, эксперименты не запускались.

| Возможность | Реализация и проверки | Production / граница знания |
| --- | --- | --- |
| Wearable-independent morning loop | Load/response/feeling → readiness → decision; [контракт модели](../models/READINESS_MODEL.md), [тесты orchestration](../../backend/tests/test_daily_readiness_pipeline.py) | [Приёмка #108, 2026-09-23](https://github.com/shchukins/whatte/issues/108#issuecomment-5802313089): два перекрывающихся 14-дневных окна; rendered-согласованность поверхностей и эффект на исходы не установлены |
| Recommendation / briefing | Общий [decision_engine](../../backend/backend/services/decision_engine.py) используется [readiness API](../../backend/backend/services/readiness_query.py) и [Telegram](../../backend/backend/services/notification_service.py); [тесты](../../backend/tests/test_notification_service.py) | Pilot подтверждает persisted delivery, но не точное историческое содержимое каждого экрана/сообщения |
| Today / Profile / Diary | [UX-контракт](../ui/READINESS_TODAY_SCREEN.md), [профиль](USER_PROFILE.md), [Today tests](../../backend/tests/test_today.py), [Diary tests](../../backend/tests/test_today_diary.py), [Profile tests](../../backend/tests/test_user_profile.py); #153/#169 закрыты | Закрытие UX-issues не доказывает отдельную live-проверку каждого сценария. [#195, 2026-10-15](https://github.com/shchukins/whatte/issues/195#issuecomment-6197434981) фиксирует production PED и Diary smoke, не полную повторную UX-приёмку |
| Optional manual physiology | API, Telegram, Web, personal-relative features и immutable research inputs: [контракт](../models/PERSONAL_PHYSIOLOGY_FEATURES.md), [тесты](../../backend/tests/test_today_physiology.py) | Отдельная production-приёмка всех entry surfaces здесь не подтверждена; manual inputs не подменяют historical physiology score, достаточность наблюдений не доказана |
| Research infrastructure / recovery predictor | Версионированные snapshots/datasets/evaluator/audit/runner и offline predictor реализованы; [приёмка и CI-свидетельство 2026-10-08](RECOVERY_RESEARCH_ACCEPTANCE.md) | #150/#136 открыты: нужна достаточная реальная выборка и отдельная home-server приёмка; research MVP #138 не принят |
| Descriptive calibration analytics | [#77 records и summary](../data/CALIBRATION_RECORDS.md), [тесты](../../backend/tests/test_calibration_records.py); joins, denominators и review cases реализованы | [#77 delivery record, 2026-09-29](https://github.com/shchukins/whatte/issues/77) фиксирует CI и read-only production smoke; numerical model-error verdict остаётся `not_measurable`, #77/#95 открыты |
| RPE history / PED / PED study | [История](../api/RPE_HISTORY.md), [PED](../models/PERCEIVED_EFFORT_DEVIATION.md), [offline study](PED_RESEARCH.md); #194–#196 закрыты | [#196: delivery verification 2026-10-16](https://github.com/shchukins/whatte/issues/196#issuecomment-6203497055) подтверждает выпуск `d9f62bf`; исследовательский вывод остаётся `insufficient evidence`, не эффективность PED |

Фокусные unit/fixture-проверки при сверке 2026-10-17: 382 passed (decision,
notification, Today, Diary, physiology form, Profile/pending, recovery predictor,
data readiness и PED study). Docker/PostgreSQL локально не перепроверялись;
сохранённое [Backend CI для `d9f62bf`](https://github.com/shchukins/whatte/actions/runs/38808135511)
подтверждает unit и DB integration jobs. Это разные уровни проверки.

---

## 1. Общий статус

Whatte перешел от load-only readiness к рабочей baseline-архитектуре Model V2.

Текущая схема:

```text
LoadState + Response + Feeling + optional Physiology -> Readiness -> GoodDayProbability
```

Система уже работает как end-to-end pipeline:

```text
Strava + Web/Telegram feedback -> backend -> daily state -> readiness -> decision
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

### 2.2 Historical physiology contour

Источник: ранее сохранённые HealthKit records. Новый ingestion остановлен.

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
- raw, normalized и recovery rows не удаляются
- historical physiology используется только для той же даты и не переносится вперёд

### 2.3 Readiness layer

Pipeline:

- `load_state_daily_v2 + response + feeling + optional exact-date physiology -> readiness_daily`

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
- missing physiology имеет `unavailable` и не штрафует score
- readiness получает historical physiology через provider-neutral boundary
- `readiness_daily.explanation_json` теперь включает recovery breakdown из `health_recovery_daily.recovery_explanation_json`
- daily Telegram notification строится от `readiness_daily`, а не от legacy freshness-only summary

### 2.4 Optional manual physiology и research inputs

Web Today, Telegram и API сохраняют общие versioned manual observations;
`personal_physiology_feature_daily` содержит отдельные personal-relative features.
Это исследовательские inputs с явной missingness, без автоматической подстановки
в `health_recovery_daily` или изменения production readiness.
См. [manual physiology API](../api/MANUAL_PHYSIOLOGY.md) и
[daily feature vector v1/v2](../models/DAILY_FEATURE_VECTOR.md).

---

## 3. Data pipeline

### 3.1 Daily readiness orchestration

Flow:

1. worker определяет текущую дату в `WHATTE_TIMEZONE`
2. `load_state_daily_v2` продлевается до target date с `tss = 0` в дни без тренировок
3. readiness загружает response, feeling и optional exact-date historical physiology
4. `readiness_daily` материализуется
5. deterministic recommendation/briefing доставляется в Web Today и Telegram

### 3.2 Load model v2 recompute

Endpoint:

`POST /api/v1/model/load-state-v2/{user_id}`

Особенности:

- непрерывная календарная ось
- `load_state_daily_v2` строится до явной target date
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

Текущая versioned composition использует семейства `load`, `freshness`,
`response`, `feeling`, `physiology`. Веса нормализуются только по доступным
scored signals; точная формула зафиксирована в `docs/models/READINESS_MODEL.md`.

Важно:

- `good_day_probability` уже реализован
- это baseline probability-like mapping
- это не статистически откалиброванная вероятность
- missing physiology не считается нулём или плохим восстановлением

---

## 5. Что уже работает end-to-end

- Strava ingestion материализует training load и response metrics
- Web/Telegram сохраняют RPE и morning feeling
- [PED v1](../models/PERCEIVED_EFFORT_DEVIATION.md) сравнивает сохранённый effective RPE с медианой 3–5 похожих прошлых тренировок; показывает разброс, ограниченную надёжность и ограничения исторических правок, без влияния на readiness
- scheduled worker продлевает load state до текущей локальной даты
- `readiness_daily` работает без physiology
- historical exact-date physiology продолжает обогащать старые даты
- recommendation и briefing доступны через API, Web Today и Telegram
- Today показывает единый ответ с раскрываемым объяснением; формы сохраняют ввод
  при ошибках, используют backend-owned effective RPE и явное сохранение
- Profile ведёт датированные FTP/HR max/weight, отдельно сохраняет и пересчитывает;
  pending status виден также в Today и Diary
- Diary `/today/diary` показывает 14 локальных дней, фильтр по effective RPE,
  возврат к историческому дню, пригодность нагрузки и фактическую 7-дневную сводку
- stale-date guards и lifecycle-восстановление Today/Profile не повторяют POST;
  завершённый UX scope: [#153](https://github.com/shchukins/whatte/issues/153),
  [#169](https://github.com/shchukins/whatte/issues/169),
  [контракт и ограничения](../ui/READINESS_TODAY_SCREEN.md)

Публичный API уже проксируется через VPS / Caddy через `api.shchukin.de`.

Новый domain split:

- `shchukin.de` — web surfaces
- `shchukin.de/dashboard` — Internal Dashboard
- `api.shchukin.de` — technical API, Strava OAuth callback, Telegram webhook, `/healthz`, OpenAPI/docs when enabled

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
- deterministic formatting для Web Today / Telegram consumption

### 6.3 Subjective feedback layer

Уже реализованы:

- post-ride RPE prompt
- next-day recovery prompt
- `activity_subjective_feedback`
- `subjective_feedback_prompt_log`
- `decision_context_snapshot` для append-only delivery/check-in context

Важно:

- morning feeling и usable RPE-derived response могут влиять на readiness через
  существующий [signal-family contract](../models/READINESS_MODEL.md)
- feedback сохраняется также как evaluation evidence; он не меняет веса,
  thresholds или формулы и не запускает скрытое обучение

## 7. Основные ограничения текущей версии

1. Recovery baseline уже реализован, но еще не откалиброван на популяционных или персональных outcome данных.
2. `load_input_nonlinear` пока фактически линейный.
3. `good_day_probability` пока является простым mapping от readiness score.
4. Decision layer уже реализован, но пока остается узким baseline mapping без time-aware planning и duration guidance.
5. Общий decision/briefing contract уже используется API и Telegram; presentation
   wrappers остаются разными. Историческая rendered-согласованность всех delivery
   surfaces не измерена, это не задача заново объединить decision logic.
6. Outcome calibration и принятие research MVP ждут evidence/операционной приёмки;
   наличие personal baselines и offline predictor не доказывает качество модели.

## 8. Ключевые архитектурные решения

- Load и optional historical Physiology разделены
- Readiness не равен freshness
- Readiness хранится отдельно в `readiness_daily`
- Recovery влияет на readiness, но не переписывает load model
- используется daily aggregation
- используется probability layer (`good_day_probability`)
- baseline decision layer отделен от readiness formula
- subjective feedback хранится отдельно от model state как calibration dataset
- deterministic core остается приоритетом

---

## 9. Текущие источники данных

### Реальные

- Strava
- Web/Telegram subjective feedback
- optional manual physiology через API/Web/Telegram (отдельный research contour)
- датированный профиль FTP/HR max/weight
- preserved historical HealthKit rows (read-only, exact-date only)

### Planned

- optional provider integrations behind the physiology boundary
- calendar/equipment context для более широкого planning layer

---

## 10. Research status и следующие шаги

[#150](https://github.com/shchukins/whatte/issues/150) — реализованный offline
predictor next-day recovery 1–5 с train-only fitting и MAE;
[#136](https://github.com/shchukins/whatte/issues/136) — реализованная изоляция
и audit path. Обе задачи открыты до real-data/home-server приёмки по
[acceptance runbook](RECOVERY_RESEARCH_ACCEPTANCE.md), а не из-за отсутствия
predictor-кода. Legacy v1 snapshots нельзя дополнять текущим mutable состоянием.

Последний специализированный acceptance record от 2026-10-08 ещё не подтверждал
natural v2 capture. Более новый [PED report от 2026-10-15](PED_RESEARCH.md#observed-result-2026-10-15-europemoscow)
фиксирует в рассмотренном окне 0 eligible train days, 2 validation rows и 1 compatible recovery target.
Это более позднее свидетельство v2 inputs, но не проверка всей связи natural
delivery → snapshot, не новый readiness report #150 и не успешный реальный runner.
Данных после этой даты в этом обзоре нет.

Следующая зависимость: prospective evidence → readiness/preparation gates →
достаточно покрытый реальный запуск и приёмка #150/#136 →
[#138](https://github.com/shchukins/whatte/issues/138). Инфраструктура и закрытая
#196 не означают завершение [#125](https://github.com/shchukins/whatte/issues/125)
или доказанную эффективность модели. Конкретные действия сейчас, блокеры и
отложенный backlog перечислены в [Current priorities](../ai/CURRENT_PRIORITIES.md).

---

## 11. Definition of Done для текущей стадии

Система считается рабочей на текущем этапе, если:

- training data приходит из Strava, feedback — из Web/Telegram
- считается `load_state_daily_v2`
- считается `readiness_daily`
- отсутствие physiology не блокирует daily loop
- historical HealthKit rows остаются сохранены
- `good_day_probability` доступен как отдельный output
- документация соответствует реальному backend baseline
