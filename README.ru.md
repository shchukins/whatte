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

---

## Зачем Whatte

Большинство тренировочных платформ предполагают, что жизнь подстраивается под тренировочный план. Сон, работа, встречи и усталость считаются помехой.

Whatte работает иначе.

Система учитывает восстановление, накопленную нагрузку и доступное время, чтобы определить, какая тренировка действительно уместна сегодня — а не просто следует шаблону.

Название объединяет несколько смыслов: **what today**, **watt** и главный ежедневный вопрос спортсмена — что делать сегодня?

---

## Твоя экосистема, твои данные

Whatte не требует привязки к конкретному бренду устройств или платформе.

Для анализа нагрузки можно использовать то, что у тебя уже есть: Wahoo, Zwift, Rouvy, Apple Watch, Garmin, любой велостанок или устройство, которое умеет выгружать данные в Strava или Apple Health.

Strava и Apple Health — точки подключения, а не закрытая экосистема.

---

## Что делает система

### Утренний брифинг

Система уже формирует ежедневный readiness-результат с объяснением, детерминированной зоной рекомендации и кратким briefing-текстом для API, Telegram и iOS.

Не только метрики, но и интерпретацию состояния.

---

### Детерминированные рекомендации

Текущий baseline переводит readiness в явную рекомендацию: `recovery`, `endurance`, `moderate` или `high_intensity`.

Более широкий decision layer с учетом календаря, доступного времени и выбора длительности остается следующим этапом, а не текущей реализованной возможностью.

---

### Объяснимые выводы

Каждая рекомендация сопровождается причинами: снижение HRV, плохой сон, высокая накопленная усталость, недостаточное восстановление после предыдущих нагрузок.

Логика рекомендаций остаётся прозрачной и проверяемой.

---

## Как это работает

```text
Strava + Apple Health
        ↓
модель нагрузки + модель восстановления
        ↓
оценка состояния + факторы влияния
        ↓
рекомендация на день
        ↓
утренний брифинг
```

Ядро системы детерминированное и воспроизводимое.  
ИИ используется как вспомогательный слой, а не как основа продукта.

Каждый вывод можно проследить до конкретных данных, метрик и формул.

---

## Принципы

- данные принадлежат пользователю — self-hosted, без зависимости от сторонних облаков
- детерминированное ядро — одинаковые входные данные дают одинаковый результат
- объяснимость важнее иллюзии точности — пользователь видит причины рекомендаций
- независимость от экосистемы — поддерживаются любые устройства, работающие через Strava или Apple Health

---

## Статус

Активный прототип.

Основной pipeline уже работает end-to-end: данные из Strava и HealthKit ежедневно обрабатываются, рассчитываются load, recovery, readiness и детерминированный recommendation output.

Daily readiness доступен через API и Telegram delivery. Более широкий planning layer и calibration остаются в активной разработке.

---

## Операционные поверхности

- `shchukin.de` — основной web-домен для пользовательских и админских web surfaces.
- `shchukin.de/dashboard` — internal dashboard, реализованный как FastAPI SSR HTML через Jinja2.
- `api.shchukin.de` — технический API-домен для FastAPI endpoints, Strava OAuth callback, Telegram webhook, HealthKit sync, `/healthz` и API docs when enabled.

Dashboard защищен `Caddy` Basic Auth и является текущей основной поверхностью operational monitoring для production backend на VPS. Google OAuth остается целевым будущим вариантом авторизации.

Dashboard показывает System, Connection, Ingest Jobs и Strava Activities из локального backend/database state. Он не вызывает Strava API, не refresh-ит токены, не изменяет БД и не показывает secrets.

Старый home-server Telegram watchdog / cron monitoring считается legacy и не должен восприниматься как основной production monitoring канал.

---

## Документация

- [Архитектура](docs/architecture/ARCHITECTURE.md)
- [Модель готовности](docs/models/READINESS_MODEL.md)
- [Текущее состояние](docs/product/CURRENT_STATE.md)
- [Продуктовые сценарии](docs/product/SCENARIOS.md)
- [Backend](backend/README.md)
- [Contributing](CONTRIBUTING.md)

---

## Поддержка

Whatte — независимый open-source проект. Инфраструктура и разработка финансируются самостоятельно — если хочешь помочь, буду рад [Telegram Stars](https://t.me/humanengine_lab).