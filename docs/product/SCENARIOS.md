# Scenarios

## 1. Purpose

Этот документ описывает пользовательские сценарии Whatte.

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
2. Worker продлевает load state до текущей локальной даты
3. Readiness использует response, morning feeling и optional exact-date physiology
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

1. Пользователь открывает Web Today
2. Backend читает materialized readiness за текущую локальную дату
3. Пользователь при необходимости отправляет one-tap morning feeling
4. Backend выполняет deterministic daily recompute
5. Пользователь видит:

- readiness
- explanation
- recommendation
- 7-day trend

### Notes

- trend строится из `readiness_daily` history
- history endpoint не делает recompute
- load state должен продолжаться по календарю без зависимости от wearable sync
- recommendation строится из текущего `readiness_score`

---

## 4. Scenario: Today screen

### Context

- пользователь открывает mobile-friendly Web Today
- экран читает daily readiness и backend-owned recommendation
- отсутствие physiology показывается как optional unavailable

### User sees

- readiness score
- status text
- recommendation
- compact 14-local-day table of persisted readiness, recommendation category,
  and morning recovery feedback
- freshness signal
- optional physiology signal
- historical physiology breakdown when the same-date record exists:
  - sleep score
  - HRV score
  - resting HR score

### Implemented data sources

- `GET /api/v1/model/readiness-daily/{user_id}/{date}`
- internal calendar-window read of `readiness_daily` and
  `activity_subjective_feedback` for the protected Today page
- `readiness_daily`
- `explanation.recovery_explanation`

### Notes

- Web Today displays current backend state
- recommendation is deterministic
- UI does not run model logic locally
- history covers today and the preceding 13 dates in the configured local
  timezone; missing dates and feedback remain visible as missing
- the table is current persisted history, which may change after recomputation;
  it is not an immutable record of morning decisions or delivered messages
- model versions are shown separately, and recommendation categories are mapped
  only for the supported current version through the shared decision contract
- a history read failure affects only the history section

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
