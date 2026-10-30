# Whatte

[English version](README.md)

<p align="center">
  <img src="https://img.shields.io/badge/статус-активный%20прототип-blue" />
  <img src="https://img.shields.io/badge/лицензия-MIT-yellow" />
  <img src="https://img.shields.io/badge/интеграция-Strava-FC4C02" />
  <a href="https://t.me/humanengine_lab">
    <img src="https://img.shields.io/badge/Telegram-Whatte-2CA5E0?logo=telegram" />
  </a>
</p>

<p align="center">
  <strong>Что сегодня?</strong>
</p>

**WHATTE — Adaptive Training Decision Engine.**

Продуктовый ориентир — помочь выбрать наиболее полезную тренировку сегодня
с учётом долгосрочной цели, выполненной работы и доступного времени недели.

## Задача

План предусматривает двухчасовую длительную, а осталось 50 минут. Сократить,
заменить, перенести или отдохнуть? WHATTE должен объяснить компромисс и помочь
сохранить смысл тренировочного процесса. Больше TSS и выше readiness сами по
себе не означают больше прогресса.

## Что уже работает

Текущий прототип собирает Strava activities и Web/Telegram feedback, считает
load, response и readiness, выдаёт детерминированную категорию
`recovery`, `endurance`, `moderate` или `high_intensity` и shared briefing.
Есть датированный профиль, RPE guidance/history, Today/Diary и read-only
операционный dashboard. Historical HealthKit rows сохранены; ingestion и
iOS-клиент retired. Optional manual physiology существует как отдельный
исследовательский контур.

Категория по readiness сохранена. Today также использует детерминированную
`training_time_policy_v1`: ручной приоритет блока, недельный план, фактические
активности и подтверждённые окна. Изменение сегодняшних минут даёт предложение
с компромиссами и альтернативами, без применения изменений плана. Разрешения
и совместимость переноса задаются явно. Принятие решения и связь активности
с планом остаются planned. Это не готовый тренер или автоматический планировщик.

## Следующий эксперимент — planned

Один велосипедист, один блок, ручной план, доступное время как первое изменяемое
ограничение. Простые правила сравнивают сокращение, замену, перенос и отдых,
показывают сохраняемый/потерянный стимул и предлагаемые изменения недели.
[Граница MVP](docs/product/TRAINING_DECISION_MVP.md).

Успех: полезные решения при изменении обстоятельств и наблюдаемый прогресс
по согласованным контрольным заданиям. Выполнение плана и рост модельного
`fitness` не доказывают улучшение формы; один блок не доказывает эффект WHATTE.

## Приоритеты

Readiness/recovery остаются вспомогательным контекстом. Усложнение HRV/RHR/sleep,
recovery prediction и autoresearch приостановлено как направление разработки;
их калибровка не блокирует первый эксперимент. Работающий runtime и сохранённые
данные этим решением не меняются.

## Принципы

- Детерминированное ядро и backend-owned решение.
- Объяснимые компромиссы, версии правил и воспроизводимость.
- Явная missingness; отсутствие данных не равно хорошему состоянию.
- Нет обязательного wearable, LLM или мобильного приложения.
- Сначала простые правила и сравнение с простым baseline; затем усложнение по evidence.

## Операционные поверхности

- [`shchukin.de`](https://shchukin.de) — основной web-домен
- [`shchukin.de/dashboard`](https://shchukin.de/dashboard) — внутренний операционный dashboard на FastAPI SSR
- [`api.shchukin.de`](https://api.shchukin.de) — технический API-домен

Dashboard показывает локальное состояние backend и базы данных в разделах System, Connection, Ingest Jobs и Strava Activities. Он работает только на чтение, не вызывает Strava, не обновляет токены и защищён на уровне Caddy с помощью Basic Auth.

## Документация

- [Продуктовая концепция](docs/ai/PRODUCT_CONTEXT.md)
- [Текущие приоритеты](docs/ai/CURRENT_PRIORITIES.md)
- [Граница первого эксперимента](docs/product/TRAINING_DECISION_MVP.md)

- [Архитектура](docs/architecture/ARCHITECTURE.md)
- [Модель готовности](docs/models/READINESS_MODEL.md)
- [Текущее состояние](docs/product/CURRENT_STATE.md)
- [Продуктовые сценарии](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Contributing](CONTRIBUTING.md)
