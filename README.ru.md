# Whatte

[English version](README.md)

<p align="center">
  <img src="https://img.shields.io/badge/статус-активный%20прототип-blue" />
  <img src="https://img.shields.io/badge/лицензия-MIT-yellow" />
  <img src="https://img.shields.io/badge/интеграция-Strava-FC4C02" />
  <img src="https://img.shields.io/badge/iOS-HealthKit-black" />
  <a href="https://t.me/humanengine_lab">
    <img src="https://img.shields.io/badge/Telegram-Whatte-2CA5E0?logo=telegram" />
  </a>
</p>

<p align="center">
  <strong>Что сегодня?</strong>
</p>

Whatte — приложение и backend-система, которые объединяют данные о тренировочной нагрузке, восстановлении и контексте пользователя, чтобы помочь принять практическое решение на день: интенсивная тренировка, лёгкая нагрузка, восстановление или отдых.

## Задача

Статический тренировочный план не учитывает реальную жизнь. Сон, работа, усталость и предыдущие тренировки меняют состояние человека, даже если в календаре ничего не изменилось.

Поэтому важно понимать не только то, что записано в плане, но и какая нагрузка уместна именно сегодня.

## Как отвечает Whatte

Whatte:

- собирает тренировочные данные из Strava и recovery-данные из Apple Health
- рассчитывает load, recovery и readiness в отдельных, трассируемых слоях
- объясняет, какие факторы повлияли на результат
- детерминированно переводит readiness в рекомендацию на день

## Что уже работает

- ingestion тренировок из Strava и обработка webhooks
- ingestion HealthKit-данных через iOS-клиент
- сохранение raw-данных и нормализованные health-данные
- модели ежедневной нагрузки и восстановления
- объяснимый daily readiness
- детерминированные категории рекомендаций: `recovery`, `endurance`, `moderate` и `high_intensity`
- компактный briefing output для API, Telegram и iOS-friendly surfaces
- read-only внутренний операционный dashboard

## Что планируется

- более широкий decision layer поверх текущего readiness-to-category mapping
- логика с учётом календаря
- рекомендации по длительности и времени тренировки
- калибровка readiness и явная персонализация
- дальнейшее развитие пользовательского мобильного приложения

Эти возможности не входят в текущий production baseline.

## Как это работает

```text
Strava + Apple Health
        ↓
load + recovery
        ↓
readiness
        ↓
детерминированная рекомендация
        ↓
ежедневный брифинг
```

## Принципы

- **Детерминированное ядро.** Одинаковые входные данные дают одинаковый результат.
- **Объяснимость.** Рекомендацию можно проследить до данных, метрик и правил.
- **Воспроизводимость.** Raw-данные сохраняются, а derived state можно пересчитать.
- **Независимость от экосистемы.** Strava и Apple Health — точки подключения, а не привязка к конкретному оборудованию.
- **ИИ — вспомогательный слой.** Он может помогать с объяснениями и текстом, но не рассчитывает состояние и не принимает решения.

## Текущий статус

Whatte — активный прототип. Основной backend pipeline работает end-to-end: данные из Strava и HealthKit проходят нормализацию и используются для расчёта daily load, recovery, readiness, детерминированной категории рекомендации и briefing output.

Текущий recommendation layer намеренно ограничен. Он помогает принять решение на день, но пока не является полноценным тренировочным планировщиком.

## Операционные поверхности

- [`shchukin.de`](https://shchukin.de) — основной web-домен
- [`shchukin.de/dashboard`](https://shchukin.de/dashboard) — внутренний операционный dashboard на FastAPI SSR
- [`api.shchukin.de`](https://api.shchukin.de) — технический API-домен

Dashboard показывает локальное состояние backend и базы данных в разделах System, Connection, Ingest Jobs и Strava Activities. Он работает только на чтение, не вызывает Strava, не обновляет токены и защищён на уровне Caddy с помощью Basic Auth.

## Документация

- [Архитектура](docs/architecture/ARCHITECTURE.md)
- [Модель готовности](docs/models/READINESS_MODEL.md)
- [Текущее состояние](docs/product/CURRENT_STATE.md)
- [Продуктовые сценарии](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Contributing](CONTRIBUTING.md)

## Поддержка

Whatte — независимый open-source проект. Инфраструктура и разработка финансируются самостоятельно. Поддержать проект можно через [Telegram Stars](https://t.me/humanengine_lab).
