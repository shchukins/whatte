# Whatte Backend

Whatte backend — FastAPI-сервис и orchestration слой для ingestion, нормализации данных и расчета daily state.

## Назначение

Backend отвечает за:

- прием данных из внешних источников
- сохранение raw payloads
- нормализацию данных
- расчет derived daily state
- предоставление API для пересчета и интеграции

## Принципы

- deterministic logic first
- прозрачные вычисления
- воспроизводимость через raw storage
- минимальная скрытая магия
- AI не участвует в core-расчетах

## Текущая архитектура

Источники:

- Strava
- subjective feedback from Web and Telegram
- historical HealthKit rows as optional exact-date physiology

Базовый поток:

```text
Strava -> raw ingest -> daily load -> load_state_daily_v2 --+
subjective feedback -> feeling / response ------------------+-> readiness
historical health_recovery_daily (exact date, optional) -----+
```

Деплой:

```text
Internet
↓
VPS (Caddy reverse proxy)
↓
FastAPI + PostgreSQL
```

Текущий production backend работает на VPS. `api.shchukin.de` остается техническим API-доменом, а `shchukin.de/dashboard` проксируется Caddy на internal dashboard в том же FastAPI backend process. Старый home-server deployment / watchdog context считается legacy и не является основной production-схемой.

## Реализованные backend layers

### 1. Strava ingestion

- webhook endpoint
- Telegram callback endpoint for inline post-ride and next-day recovery feedback
- worker-driven scheduled next-day recovery prompt orchestration
- raw storage
- ingest jobs
- загрузка активностей
- формирование `daily_training_load`

### 2. Historical physiology storage

HealthKit collection is retired and no `/api/v1/healthkit/*` routes are
exposed. Existing raw, normalized, and recovery rows remain intact. The legacy
processing services remain for deliberate local replay of already stored raw
payloads, not as an active ingestion path.

### 3. Historical health normalized layer

Реализованы таблицы:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

Назначение:

- сохранять ранее полученные HealthKit records в детерминированной форме
- отделить raw payload от прикладных расчетов

### 4. Recovery layer

Реализована таблица:

- `health_recovery_daily`

Текущий baseline включает:

- sleep metrics
- resting HR
- HRV daily median
- latest known weight
- `recovery_score_simple`
- `recovery_explanation_json`

Текущая recovery baseline-логика:

- использует baseline-aware scoring
- считает `hrv_baseline` и `rhr_baseline` по предыдущему окну
- считает `hrv_dev` и `rhr_dev`
- считает component scores:
  - `sleep_score`
  - `hrv_score`
  - `rhr_score`
- сохраняет breakdown в `recovery_explanation_json`

Важно:

- поле по-прежнему называется `recovery_score_simple` для совместимости схемы и API
- по смыслу это уже не purely naive heuristic-only score
- новые recovery rows из HealthKit в production больше не собираются

### 5. Load model v2

Реализована таблица:

- `load_state_daily_v2`

Текущий расчет:

- идет по непрерывной календарной оси
- продлевается до явной `through_date`, не используя physiology как calendar driver
- использует `tss = 0` в дни без тренировок
- использует текущий линейный input по TSS
- хранит `fitness`
- хранит `fatigue_fast`
- хранит `fatigue_slow`
- хранит `fatigue_total` как взвешенную смесь fast/slow fatigue
- хранит `freshness = fitness - fatigue_total`

Параметры:

- `tau_fitness = 40`
- `tau_fatigue_fast = 4`
- `tau_fatigue_slow = 9`

### 6. Readiness layer

Реализована таблица:

- `readiness_daily`

Текущий readiness baseline (`v2_signal_composition_response_v1`):

- публикует независимые семейства `load`, `freshness`, `response`, `feeling`, `physiology`
- работает от `freshness` без HealthKit
- использует date-level `next_day_recovery` как optional first-class `feeling`
- использует exact-date historical `recovery_score_simple` как optional `physiology`
- нормализует веса только по доступным scored-семействам; missing physiology не штрафует score
- сохраняет legacy `v2` и `v2_signal_composition` rows отдельно
- сохраняет `readiness_score`
- сохраняет `good_day_probability`
- сохраняет `status_text`
- сохраняет `explanation_json`

Важно:

- readiness хранится отдельно от `load_state_daily_v2`
- readiness не равен `freshness`
- `load` не получает отдельный score поверх `freshness`, чтобы не учитывать одну нагрузку дважды
- `response` читает versioned `activity_response_metrics` и использует только
  comparable-session baseline deviations; без пригодного baseline остается
  context-only и не меняет readiness score
- response имеет maximum configured weight `0.2`, который уменьшается с
  возрастом activity; raw load/RPE не учитываются напрямую
- текущий `good_day_probability` является baseline probability-like mapping:
  - `good_day_probability = readiness_score / 100`
  - это не статистически откалиброванная вероятность
- `explanation_json` включает recovery breakdown из `health_recovery_daily.recovery_explanation_json`

Recovery breakdown внутри `explanation_json.recovery_explanation`:

- `sleep_score`
- `hrv_score`
- `rhr_score`
- `hrv_baseline`
- `rhr_baseline`
- `hrv_dev`
- `rhr_dev`

### 7. Training response layer

Реализована таблица:

- `activity_response_metrics`

Текущий scope `v2_rpe_1_10`; `v1` остаётся историческим 1–5:

- average / normalized power и average HR
- power-to-HR relationships
- aerobic decoupling для явно eligible steady workouts
- RPE, session-RPE load и отношения RPE к IF/TSS
- median baseline по предыдущим comparable activities
- per-metric availability и reason codes

Response пересчитывается после activity pipeline и при изменении effective
RPE 1–10.
Readiness получает latest seven-day response context и строит aggregate score
внутри readiness formula. Response rows по-прежнему не хранят
synthetic aggregate response score.

Подробный контракт: [`docs/models/TRAINING_RESPONSE.md`](../docs/models/TRAINING_RESPONSE.md).

### 8. Subjective feedback layer

Реализованы таблицы:

- `activity_subjective_feedback`
- `activity_rpe_observation` и `activity_rpe_resolution`
- `decision_context_snapshot`

Текущий scope:

- source-aware post-ride RPE 1–10 из Telegram, Web и Strava
- next-day recovery feedback из Telegram
- activity-level и date-level subjective feedback
- normalized queryable fields + extensible payload + historical context snapshot
- activity-level idempotent upsert по `(strava_activity_id, feedback_type)` when `strava_activity_id is not null`
- date-level idempotent upsert по `(user_id, activity_date, feedback_type)` when `strava_activity_id is null`

Архитектурный смысл:

- normalized fields нужны для stable queries и analytics
- `feedback_payload` хранит feedback-type-specific детали без раздувания core schema
- `context_json` хранит readiness / recommendation snapshot на момент ответа
- snapshot сохраняется исторически для later calibration, а не пересчитывается на чтении
- delivery и recovery check-in boundaries сохраняются append-only для pilot report

Важно:

- это не ML layer
- исторический post-ride RPE 1–5 остаётся в исходной таблице; новый
  effective RPE 1–10 используется отдельной версией response
- date-level `next_day_recovery` является явным `feeling` input для
  `v2_signal_composition_response_v1`; после upsert readiness пересчитывается
  детерминированно

## Internal dashboard surface

The internal dashboard is implemented as a backend-owned operational monitoring surface.

Current properties:

- route: `/dashboard`
- public path: `https://shchukin.de/dashboard`
- rendering: FastAPI server-side rendered HTML
- templates: Jinja2 under `backend/backend/templates/dashboard/`
- dashboard code: `backend/backend/dashboard/`
- styling: minimal CSS only
- no React, Vue, Svelte, SPA, or frontend build step
- protected at the edge with `Caddy` Basic Auth

Current sections:

- `System`
- `Connection`
- `Ingest Jobs`
- `Strava Activities`

Current data layer:

- `System`: backend status, database status via existing `get_conn()` / `SELECT 1`, server time, process started time, uptime, and database error fallback
- `Connection`: Strava connection status, athlete id, scope, token expiry, and token state
- `Ingest Jobs`: latest ingest jobs plus pending and failed/error counts
- `Strava Activities`: latest locally stored activities with total count, name/type/date/distance/time

Important constraints:

- dashboard route remains read-only
- database errors must not crash `/dashboard`
- a failing dashboard section must degrade safely instead of breaking the whole page
- dashboard reads local database/backend state; it must not call Strava API
- dashboard must not refresh Strava tokens or perform side effects
- dashboard must not expose `access_token`, `refresh_token`, passwords, or other secrets
- Google OAuth restricted to an allowed user remains a future authorization improvement, not current behavior

Operational role:

- dashboard is the primary operational monitoring surface for the current VPS production backend
- Telegram alerts and the old home-server watchdog are legacy/secondary and should not be developed as the main monitoring channel right now
- dashboard is not a full alerting system; it is a read-only status and pipeline inspection surface

## Web Today surface

The mobile-friendly daily interaction surface is implemented as backend-owned
server-rendered HTML.

- route: `/today`
- public path: `https://shchukin.de/today`
- current user: configured by `DAILY_READINESS_USER_ID`
- rendering: FastAPI + Jinja2, without a frontend framework or build step
- access: Caddy Basic Auth on `shchukin.de`; UI routes return `404` on the API domain

The surface reads the current-version readiness response and displays its
backend-owned recommendation, briefing, signal-family availability, and source
freshness. Missing physiology remains `unavailable`; the web layer does not
convert missing data into a score and does not duplicate readiness logic.

The two write paths reuse the existing subjective-feedback services:

- today's `next_day_recovery` on the 1-5 scale; an idempotent upsert is followed
  by deterministic readiness recomputation for the same date;
- `post_ride_rpe` on the 1-10 scale for the latest eligible canonical
  activity, displaying its effective score/source and preserving an explicitly
  selected activity for edit.

Both feedback types use `source=web`. Repeated RPE submissions update the
Web observation while recovery submissions update their date-level row. Native forms validate scores
server-side, reject cross-site submissions, and use POST/redirect/GET back to
`#recovery` or `#rpe` (retaining the selected activity). Saved scores collapse
into a compact summary; “Изменить” opens the scale with its saved Web choice,
including without JavaScript. Effective RPE and its source remain separate.
With JavaScript, the whole corresponding scale is disabled while saving.
HTTP errors, lost responses, or an unconfirmed redirected read never trigger an
automatic second POST: users can check stored state via GET or explicitly retry.
Status messages confirm the observed saved score, not successful readiness
recomputation.

## Daily readiness pipeline

Текущий core orchestration pipeline:

```text
configured local date
    -> recompute load_state_daily_v2 through target date
    -> load response + feeling + optional exact-date historical physiology
    -> recompute readiness_daily
    -> deterministic recommendation / briefing
```

Timezone задаётся `WHATTE_TIMEZONE` (по умолчанию `Europe/Moscow`). Историческая
physiology используется только при совпадении даты и никогда не переносится на
текущий день.

## Telegram daily readiness notification

Daily Telegram briefing в текущем backend использует `readiness_daily` как source of truth.

Основной утренний триггер — worker schedule. Перед delivery worker материализует
load state и readiness за текущую локальную дату. Настраиваемое расписание
`DAILY_READINESS_FALLBACK_HOUR_UTC` и
`DAILY_READINESS_FALLBACK_MINUTE_UTC` задают время запуска (по умолчанию
`07:30 UTC`).

Optional physiology состояния:

- `fresh` — exact-date historical physiology существует
- `missing` — physiology для целевой даты отсутствует; это штатный optional state

Сообщение показывает generic physiology availability, а не ошибку HealthKit.
Дневной unique row в `notification_log` сохраняет idempotent delivery lifecycle.

Основные поля:

- `readiness_score`
- `status_text`
- `good_day_probability`
- `explanation_json.freshness`
- `explanation_json.recovery_score_simple`
- `explanation_json.recovery_explanation`

Формат сообщения:

- заголовок
- readiness score
- status text
- good day probability
- freshness
- recovery score
- recovery breakdown:
  - сон
  - HRV
  - пульс покоя
- короткий rule-based комментарий

Fallback:

- если `readiness_daily` для пользователя недоступен, backend может использовать старый fallback summary

## Telegram post-ride feedback

После `notify_training_processed` backend отправляет второе Telegram message с inline RPE buttons.

Перед обеими отправками backend разрешает canonical activity. Исключённый дубль
не отправляется, а unique claims в `activity_delivery_log` обеспечивают
идемпотентность при webhook retry/update/backfill и при любом порядке прихода
MyWhoosh/Garmin.

Текущий callback format:

- `rpe10:{activity_id}:{score}` для шкалы 1–10
- старый `rpe:{activity_id}:{score}` однозначно распознаётся как 1–5 и
  отклоняется с просьбой повторить ввод в Web Today

После callback backend:

- валидирует activity
- разрешает старый Garmin activity id до canonical MyWhoosh id
- upsert-ит независимое наблюдение в `activity_rpe_observation`
- сохраняет `source = telegram`, `scale_version = rpe_1_10`, payload и время
- разрешает один effective RPE с приоритетом Strava
- пересчитывает response/readiness только при изменении effective score
- best-effort подтверждает callback и редактирует сообщение

Indoor дедупликация запускается после сохранения raw/metrics и до пересчёта
агрегатов. Она использует фактические интервалы тренировок, source metadata и
именованные overlap/duration/start thresholds. Garmin остаётся в raw и metrics,
но получает `is_excluded=true`; `daily_training_load` исключает такую запись.

## Telegram next-day recovery feedback

Backend может отправить next-day recovery prompt для конкретной даты, если предыдущий день выглядел как тренировочный.

Prompt usefulness:

- `daily_training_load.tss > 0`
- или `daily_training_load.activities_count > 0`
- или есть activities в `strava_activity_raw` за предыдущую дату

Текущий callback format:

- `recovery:{user_id}:{target_date}:{score}`

После callback backend:

- валидирует `target_date` и `score`
- upsert-ит row в `activity_subjective_feedback`
- пишет `feedback_type = next_day_recovery`
- пишет `activity_date = target_date`
- оставляет `strava_activity_id = null` для date-level semantics
- сохраняет previous-day linkage в `feedback_payload`
- сохраняет historical readiness / recommendation context, если доступно
- best-effort подтверждает callback
- best-effort редактирует сообщение в `Recovery feedback recorded ✓`

Telegram UX philosophy:

- feedback optional
- low-friction longitudinal collection
- one-tap answer в текущем MVP
- максимум три taps как потолок для будущих flows

Debug endpoint для ручной проверки:

- `POST /debug/feedback/recovery-prompt/{user_id}/{target_date}`


## Технологический стек

Backend:

- FastAPI
- Python
- PostgreSQL

Infrastructure:

- Docker
- Docker Compose
- Caddy
- Tailscale

External integrations:

- Strava API
- Strava Webhooks

## Структура проекта

`backend/`  
Основной код backend-сервиса на FastAPI.

`backend/infra/`  
Локальная инфраструктура для разработки.

`db-init/`  
SQL для инициализации базы данных.

`compose.yaml`  
docker compose стек для сервера.

## Roadmap

Уже реализовано:

- preserved historical HealthKit raw/normalized/recovery storage
- recovery daily aggregation
- recovery explanation payload
- load model v2 baseline
- readiness baseline
- good day probability baseline

Следующие шаги:

- activity streams ingestion
- расширение feature extraction
- калибровка readiness / probability
- decision layer / recommendation layer
- API и UI для user-facing insights

## AI Context

See:

- `docs/ai/PRODUCT_CONTEXT.md`
- `docs/ai/CURRENT_PRIORITIES.md`
- `AGENTS.md`

## Run locally

### Requirements

- Docker
- Docker Compose
- Python 3.11+

### 1. Clone repository

```bash
git clone https://github.com/shchukins/whatte.git
cd whatte/backend
```

### 2. Create environment file

```bash
cp infra/.env.example infra/.env
```

### 3. Start PostgreSQL

```bash
cd infra
docker compose up -d
```

PostgreSQL:

- host: `localhost`
- port: `5433`
- database: `human_engine`

### 4. Install backend dependencies

```bash
cd ..
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Run backend

```bash
uvicorn backend.app:app --reload
```

API:

- `http://localhost:8000`
- health check: `http://localhost:8000/healthz`


## Scheduled next-day recovery prompt

The backend worker now schedules next-day recovery prompts once the current UTC hour matches `NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC` (default `7`).

Current V1 behavior:

- looks at the previous UTC day for training load or activities
- skips users who already submitted `next_day_recovery` feedback for the target date
- persists delivery state in `subjective_feedback_prompt_log`
- prevents duplicate sends across repeated worker loops
- keeps the single-user debug endpoint and adds a batch debug endpoint at `POST /debug/feedback/recovery-prompts/{target_date}`

Current limitation:

- scheduling is UTC-based because per-user timezone orchestration is not implemented yet

## User profile

Web Today includes `/today/profile` for independent dated FTP, HR max and weight inputs
and explicit historical recalculation. Apply migrations `011_user_profile.sql`
and `020_user_profile_hr_max.sql`
before deploying this version to backend and worker. See
[profile behavior and deployment](../docs/product/USER_PROFILE.md).

Перед выпуском RPE 1–10 применить `db-init/012_rpe_observations.sql` к
существующей БД, затем обновить backend и worker вместе. Миграция оставляет
исторические feedback 1–5 и response `v1` без преобразования; новый response
`v2_rpe_1_10` собирает собственный comparable baseline.

Перед использованием manual-only personal physiology features применить
`db-init/015_personal_physiology_features.sql`. Это отдельный research-derived
слой: он не меняет readiness, Telegram flow или historical HealthKit rows.

## Isolated research runner (#136)

The infrastructure CLI is `python -m scripts.run_research_experiment`. It uses
a separate research image and dedicated audit writer credentials; see
[runner contract and operational prerequisites](../docs/product/RESEARCH_RUNNER.md).
The legacy readiness recipe remains unsupported for outcome prediction, so its built-in
candidate worker explicitly records an unsupported failure. Synthetic tests
validate the execution protocol, not scientific readiness/outcome prediction.


## Offline recovery predictor (#150)

The reviewed day-level v2 predictor and train-only preparation are implemented;
see [model contract](../docs/models/RECOVERY_PREDICTION.md). Export with
--dataset-version temporal_dataset_v2, prepare frozen state with
python -m scripts.prepare_recovery_prediction, then supply --learned-state
to the existing runner. V1 configs/evidence retain their semantics.
Prospective capture rollout, real coverage and home-server acceptance are pending.

### Recovery research data readiness

Before preparing #150 artifacts, run `python -m scripts.report_recovery_data_readiness --dataset /private-research/dataset.json --fit-as-of FIT_AS_OF_ISO_TIMESTAMP`. It reads a test-withheld `temporal_dataset_v2` JSON export and prints aggregate gates without fitting or database access. Exit codes: 0 ready for preparation, 2 insufficient data, 1 invalid input. Potential validation coverage does not prove actual paired acceptance. See [the runbook](../docs/product/RECOVERY_RESEARCH_ACCEPTANCE.md).
