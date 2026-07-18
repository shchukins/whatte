# Ride Briefing

## 1. Purpose

Этот документ описывает, как Whatte должен формировать ride briefing поверх текущей readiness layer.

Ride briefing — это пользовательский вывод системы перед тренировкой.

Цель:

- перевести readiness state в понятную рекомендацию
- сохранить детерминированность
- опираться на уже реализованные backend layers

---

## 2. Principles

Ride briefing должен быть:

- deterministic
- кратким
- понятным
- основанным на явных правилах

Нельзя:

- генерировать briefing свободным LLM-текстом
- использовать скрытую логику
- выдавать рекомендации, которые нельзя объяснить через readiness inputs

---

## 3. Current backend basis

На текущем этапе ride briefing должен опираться на уже реализованные слои:

- `health_recovery_daily`
- `load_state_daily_v2`
- `readiness_daily`

Это важно, потому что:

- readiness больше не равен freshness
- briefing должен учитывать двухконтурную модель `load + recovery`
- вероятность хорошего тренировочного дня уже выделена в отдельный слой

---

## 4. Inputs

Практический вход для ride briefing:

- `readiness_score`
- `status_text`
- `recommendation`
- `reason`
- `explanation_json`

`recommendation` и `reason` приходят из deterministic decision layer. Ride briefing не пересчитывает readiness, load, recovery, freshness, HRV или sleep.

`good_day_probability`, `freshness` и `recovery_score_simple` могут отображаться рядом в UI или notification, но не являются отдельным источником текстовой рекомендации.

---

## 5. Output structure

Ride briefing должен содержать:

### 5.1 Briefing

Короткий пользовательский текст:

```json
{
  "briefing": "Сегодня нормальная готовность. Рекомендуется спокойная аэробная тренировка.",
  "recommendation": "endurance",
  "reason": "Readiness score is 56.5/100. Recommendation is endurance."
}
```

`briefing` предназначен для Today screen, Telegram и ride briefing endpoint. Это не raw JSON для пользователя; JSON является транспортным форматом API.

---

### 5.2 Recommendation

Рекомендация берется из decision layer:

- `recovery`
- `endurance`
- `moderate`
- `high_intensity`

---

### 5.3 Reason

`reason` берется из decision layer без генерации свободного текста.

Он нужен для explainability и debugging, но основной user-facing комментарий должен быть `briefing`.

---

### 5.4 Optional constraints

Если нужно, briefing может содержать ограничения:

- избегать высокой интенсивности
- ограничить длительность
- не делать второй тяжелый день подряд

Эти ограничения должны появляться только как явные rule-based additions.

---

## 6. Mapping rules

Текущее требование к mapping:

- опираться на `readiness_score`
- использовать `recommendation` и `reason` из decision layer
- не сводить решение только к `freshness`
- сохранять объяснимую связь с recovery layer

Текущий baseline mapping:

- `< 40` -> `recovery`
- `40 <= score < 60` -> `endurance`
- `60 <= score <= 75` -> `moderate`
- `> 75` -> `high_intensity`

Текстовые шаблоны:

| Recommendation | Briefing guidance |
| --- | --- |
| `recovery` | восстановление или очень легкая нагрузка |
| `endurance` | спокойная аэробная тренировка |
| `moderate` | умеренная аэробная тренировка |
| `high_intensity` | интенсивная работа допустима, если она есть в плане |

При missing readiness используется conservative fallback: легкая нагрузка или отдых.

---

## 7. Format requirement

Формат ride briefing должен быть стандартизирован.

Пример структуры:

- Status: `Нормальная готовность`
- Recommendation: `Moderate load`
- Reason: `Load contour stable, recovery score supports normal training`

Для UI могут существовать разные представления, но логическая структура должна оставаться одинаковой.

---

## 8. Determinism requirement

При одинаковых входных данных ride briefing должен быть одинаковым.

Это означает:

- одинаковый статус
- одинаковая категория нагрузки
- одинаковое объяснение по шаблону

Briefing не использует LLM, ML или AI generation. Он является rule-based formatting layer поверх уже рассчитанных readiness и decision outputs.

---

## 9. Not in scope

На текущем этапе ride briefing не включает:

- свободный coaching text
- разговорный AI-стиль
- скрытые эвристики вне readiness layer
- длинные персонализированные советы

---

## 10. Future extensions

В будущем можно добавить:

- тип целевой тренировки
- рекомендуемую длительность
- ограничения по зонам мощности или пульса
- дополнительный explainability layer

Но только после фиксации decision mapping поверх текущего readiness baseline.

---

## 11. Debugging

Если ride briefing кажется неверным, проверять:

1. `health_recovery_daily`
2. `load_state_daily_v2`
3. `readiness_daily`
4. mapping rule from readiness to recommendation

---

## 12. Design constraint

Ride briefing должен оставаться частью deterministic decision layer.

Любое изменение должно:

- сохранять объяснимость
- сохранять воспроизводимость
- опираться на уже реализованные backend layers
