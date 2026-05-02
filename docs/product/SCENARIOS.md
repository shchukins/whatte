# Scenarios

## 1. Purpose

Этот документ описывает пользовательские сценарии Human Engine.

Цель:

- связать систему с реальным использованием
- показать, как формируется ценность
- зафиксировать ключевые user flows

---

## 2. Core scenario

### Daily training decision

Основной сценарий системы:

> пользователь хочет понять, в каком состоянии он находится сегодня и насколько день выглядит подходящим для нагрузки

### Flow

1. Пользователь открывает систему
2. Auto sync обновляет последние HealthKit данные
3. Пересчитываются recovery, load state и readiness
4. Система возвращает status / score / probability и explanation
5. Decision layer возвращает recommendation / reason / briefing
6. Пользователь принимает решение

### Output

Пользователь получает:

- текущий статус готовности
- readiness score
- good day probability
- recommendation
- краткое объяснение

Комментарий:

- readiness output уже реализован в backend
- history endpoint отдает последние daily points для trend UI

---

## 3. Daily usage (MVP)

### Flow

1. Пользователь открывает iOS app
2. `SyncCoordinator` запускает auto sync
3. Backend сохраняет HealthKit payload и выполняет deterministic recompute
4. Today screen читает актуальный readiness state
5. Пользователь видит:

- readiness
- explanation
- recommendation
- 7-day trend

### Notes

- trend строится из `readiness_daily` history
- history endpoint не делает recompute
- readiness должен быть доступен по непрерывной daily history без gaps
- recommendation строится из текущего `readiness_score`

---

## 4. Scenario: Today screen

### Context

- пользователь открывает iOS Today screen
- HealthKit auto sync может обновить последние данные
- экран читает daily readiness и history endpoints

### User sees

- readiness score
- status text
- recommendation
- readiness trend
- freshness signal
- recovery signal
- recovery breakdown:
  - sleep score
  - HRV score
  - resting HR score

### Implemented data sources

- `GET /api/v1/model/readiness-daily/{user_id}/{date}`
- `GET /api/v1/model/readiness-daily/{user_id}/history?days=7`
- `readiness_daily`
- `explanation.recovery_explanation`

### Notes

- Today screen displays current backend state
- recommendation is deterministic
- UI does not run model logic locally

---

## 5. Scenario: After hard training block

### Context

- несколько дней высокой нагрузки
- накопленная усталость

### Expected system behavior

- снижение readiness
- снижение `good_day_probability`
- explanation через load + recovery breakdown

---

## 6. Scenario: After recovery

### Context

- период снижения нагрузки
- восстановление

### Expected system behavior

- рост readiness
- рост `good_day_probability`

---

## 7. Scenario: Stable training

### Context

- регулярные тренировки
- умеренная нагрузка

### Expected system behavior

- стабильный readiness
- стабильный readiness output без скрытой логики

---

## 8. Scenario: Load spike

### Context

- резкий рост нагрузки

### Expected system behavior

- корректировка readiness вниз
- корректировка probability вниз

---

## 9. Scenario: No recent data

### Context

- нет тренировок
- недостаточно данных

### Expected system behavior

- ограниченная уверенность
- fallback на доступные слои readiness

---

## 10. Scenario: Incomplete data

### Context

- отсутствуют некоторые метрики
- нет power / HR

### Expected system behavior

- использовать доступные данные
- не ломать модель
- явно ограничивать точность

---

## 11. Scenario: Long break

### Context

- длительный перерыв

### Expected system behavior

- формально возможен рост readiness за счет текущего baseline
- decision layer использует текущий readiness-to-recommendation mapping

---

## 12. System behavior expectations

Во всех сценариях система должна:

- быть предсказуемой
- быть объяснимой
- не давать противоречивые outputs между score, probability и status

---

## 13. Not in scope

Система пока не делает:

- долгосрочное планирование
- автоматическое построение тренировочных программ
- персонализированный coaching
- ML-based recommendation

---

## 14. Usage

Этот документ используется для:

- проверки логики модели
- тестирования
- проектирования UI
- работы с AI

---

## 15. Validation

Сценарии должны:

- соответствовать реальному поведению системы
- использоваться в тестах
- обновляться при изменениях логики
