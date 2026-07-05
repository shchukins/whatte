# Glossary

## 1. Data layer

### Data Engine
Слой, отвечающий за сбор, сохранение и нормализацию входных данных.

Включает:

- Strava ingestion
- HealthKit ingestion
- raw payload storage
- нормализацию source data

---

### Raw Data
Необработанные данные, полученные из внешних источников.

Примеры:

- `strava_activity_raw`
- `healthkit_ingest_raw`

Должны сохраняться без изменения для воспроизводимости.

---

### Normalized Data
Нормализованные таблицы, полученные из raw payloads.

Примеры:

- `health_sleep_night`
- `health_resting_hr_daily`
- `health_hrv_sample`
- `health_weight_measurement`

Используются как детерминированный вход для derived layers.

---

### Feature Extraction
Процесс преобразования raw и normalized data в daily features и derived state.

В текущем backend baseline расширенный отдельный feature layer еще не является центральным persisted слоем. Основные deterministic daily layers уже строятся напрямую из raw и normalized данных.

---

## 2. Modeling layer

### Physiology Model
Модель, оценивающая состояние спортсмена на основе явных физиологических контуров.

Примеры:

- load state
- recovery state
- readiness

---

### Training Load
Количественная оценка тренировочной нагрузки.

Примеры:

- TSS
- daily training load

---

### Load State
Состояние, описывающее накопление и спад тренировочной нагрузки.

В текущем backend реализовано в `load_state_daily_v2`.

---

### Recovery State
Состояние, описывающее восстановление организма независимо от load state.

В текущем backend реализовано в `health_recovery_daily`.

Recovery не заменяет fatigue, а корректирует readiness поверх load model.

Текущий baseline recovery layer уже включает:

- baseline-aware scoring
- `hrv_baseline`
- `rhr_baseline`
- `hrv_dev`
- `rhr_dev`
- explanation payload

---

### Fitness / Fatigue
Компоненты load state:

- Fitness: долгосрочная адаптация
- Fatigue Fast: быстрый отклик усталости
- Fatigue Slow: более инерционное накопление усталости
- Fatigue Total: взвешенная смесь fast и slow fatigue
- Freshness: `fitness - fatigue_total`

---

## 3. Decision layer

### Readiness
Оценка текущей готовности к нагрузке.

В текущей model v2 readiness:

- не равен `freshness`
- строится как функция `load_state + recovery_state`
- хранится отдельно в `readiness_daily`

Должен быть:

- детерминированным
- объяснимым
- проверяемым

---

### Good Day Probability
Вероятностное представление readiness.

Используется для:

- более мягкого rule-based маппинга
- отделения score от вероятностного слоя
- explainable decision support

В текущем backend это отдельное поле `good_day_probability` в `readiness_daily`.

Важно:

- сейчас это baseline probability-like mapping
- текущее вычисление: `good_day_probability = readiness_score / 100`
- это не статистически откалиброванная вероятность

---

### Recommendation
Результат decision layer.

Определяет:

- тип нагрузки
- допустимую интенсивность
- ограничения по дню

В текущем backend baseline recommendation layer уже реализован как deterministic mapping от `readiness_score`:

- `< 40` -> `recovery`
- `40 <= score < 60` -> `endurance`
- `60 <= score <= 75` -> `moderate`
- `> 75` -> `high_intensity`

Важно:

- это baseline decision support, а не полноценный training planner
- recommendation не пересчитывает readiness, а использует уже сохраненный readiness output
- более широкий planning layer остается planned

---

### Ride Briefing
Структурированный user-facing output перед тренировкой.

Должен быть:

- детерминированным
- стабильным
- опираться на readiness layer, а не на свободный текст

В текущем backend baseline ride briefing уже реализован как deterministic formatting layer поверх:

- `readiness_score`
- `status_text`
- `recommendation`
- `reason`

Важно:

- briefing используется в readiness API response и notification flows
- это не LLM-generated coaching text
- richer multi-surface briefing orchestration остается partial / evolving

---

## 4. System architecture

### Deterministic
Логика, которая:

- дает одинаковый результат при одинаковых входных данных
- не зависит от генеративных моделей

---

### Pipeline
Последовательность обработки данных:

`ingestion -> raw storage -> normalized data -> load/recovery state -> readiness -> decision`

---

### Core
Основная часть системы:

- backend
- database
- domain logic

Где выполняются все расчеты.

---

### Worker
Фоновый процесс или orchestration path, выполняющий:

- загрузку данных
- нормализацию
- перерасчет derived state

---

## 5. AI layer

### RAG
Retrieval-Augmented Generation.

Используется как вспомогательный инструмент для навигации и объяснений.

---

### LLM
Large Language Model.

Используется только для:

- генерации текста
- объяснений
- помощи разработчику

Не используется для:

- расчетов
- readiness logic
- принятия продуктовых решений

---

## 6. Principles

### Reproducibility
Возможность повторить расчет и получить тот же результат.

Требует:

- сохранения raw данных
- явной логики
- versioned derived layers там, где это уже реализовано

---

### Observability
Возможность понять:

- как получен результат
- какие данные использовались
- какой слой повлиял на итог

---

### Simplicity
Предпочтение:

- простых моделей
- явной логики
- минимальной магии
