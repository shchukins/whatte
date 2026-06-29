# Human Engine Backend

Human Engine backend — FastAPI-сервис и orchestration слой для ingestion, нормализации данных и расчета daily state.

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
- HealthKit

Базовый поток:

```text
Strava -> raw ingest / daily load ------------------+
                                                    |
HealthKit -> raw ingest -> normalized -> recovery --+-> readiness
                                                    |
                                                    v
                                         load_state_daily_v2
```

Деплой:

```text
Internet
↓
VPS (Caddy reverse proxy)
↓
Tailscale
↓
Home server
↓
FastAPI + PostgreSQL
```

## Реализованные backend layers

### 1. Strava ingestion

- webhook endpoint
- Telegram callback endpoint for inline post-ride and next-day recovery feedback
- worker-driven scheduled next-day recovery prompt orchestration
- raw storage
- ingest jobs
- загрузка активностей
- формирование `daily_training_load`

### 2. HealthKit ingestion

Реализованы:

- raw ingestion endpoint
- orchestration endpoint `POST /api/v1/healthkit/full-sync/{user_id}`
- raw table `healthkit_ingest_raw`
- pipeline raw ingest -> normalized -> recovery -> readiness

### 3. Health normalized layer

Реализованы таблицы:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

Назначение:

- привести payload HealthKit к детерминированной и пересчитываемой форме
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

### 5. Load model v2

Реализована таблица:

- `load_state_daily_v2`

Текущий расчет:

- идет по непрерывной календарной оси
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

Текущий readiness baseline:

- объединяет load contour и recovery contour
- использует `freshness` из `load_state_daily_v2`
- использует `recovery_score_simple` из `health_recovery_daily`
- считает `readiness_score_raw = 0.6 * freshness_norm + 0.4 * recovery_score_simple`
- сохраняет `readiness_score`
- сохраняет `good_day_probability`
- сохраняет `status_text`
- сохраняет `explanation_json`

Важно:

- readiness хранится отдельно от `load_state_daily_v2`
- readiness не равен `freshness`
- readiness собирается из двух контуров: load + recovery
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

### 7. Subjective feedback layer

Реализована таблица:

- `activity_subjective_feedback`

Текущий scope:

- post-ride RPE feedback из Telegram
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

Важно:

- это не ML layer
- feedback не влияет на core calculations
- feedback хранится как отдельный evaluation / calibration dataset

## Internal dashboard surface

A minimal internal dashboard is now implemented as a backend-owned operational surface.

Current properties:

- route: `/dashboard`
- rendering: FastAPI server-side rendered HTML
- templates: Jinja2 under `backend/backend/templates/dashboard/`
- dashboard code: `backend/backend/dashboard/`
- styling: minimal CSS only
- no React, Vue, Svelte, SPA, or frontend build step

Current sections:

- `System`
- `Strava` placeholder
- `Ingest Jobs` placeholder
- `Connection` placeholder
- `System Info` placeholder

Current `System` data layer:

- backend status
- database status via existing `get_conn()` and `SELECT 1`
- server time in `Europe/Moscow`
- process started time and uptime
- database error fallback without breaking dashboard rendering

Important constraints:

- dashboard route remains read-only
- database errors must not crash `/dashboard`
- operational error text must be treated carefully and must not expose secrets
- dashboard is currently unauthenticated and should be treated as temporary internal access only until edge protection is added
- immediate planned protection: `Caddy` Basic Auth for `/dashboard`

## HealthKit full sync pipeline

Текущий orchestration pipeline:

```text
POST /api/v1/healthkit/full-sync/{user_id}
    -> save raw payload
    -> process latest raw payload into normalized tables
    -> collect affected dates
    -> recompute health_recovery_daily for affected dates
    -> recompute load_state_daily_v2 up to latest recovery/training date
    -> recompute readiness_daily for affected dates
```

Важно:

- recovery пересчитывается поверх normalized health tables
- load_state_daily_v2 пересчитывается перед readiness, чтобы freshness был актуален
- readiness пересчитывается как отдельный слой
- public API уже работает end-to-end через VPS и Caddy

## Telegram daily readiness notification

Daily Telegram briefing в текущем backend использует `readiness_daily` как source of truth.

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

Текущий callback format:

- `rpe:{activity_id}:{score}`

После callback backend:

- валидирует activity
- upsert-ит row в `activity_subjective_feedback`
- сохраняет `source = telegram`
- сохраняет `feedback_schema_version = v1_extensible`
- сохраняет optional `feedback_payload` (для текущего RPE обычно `{}`)
- сохраняет snapshot readiness / recommendation context
- best-effort подтверждает callback и редактирует сообщение

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
- Apple HealthKit via iOS sync client

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

- HealthKit ingestion и normalization
- HealthKit full-sync orchestration
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
- iOS integration polish

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
git clone https://github.com/shchukins/human-engine.git
cd human-engine/backend
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
