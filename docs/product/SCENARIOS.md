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
5. Пользователь принимает решение

### Output

Пользователь получает:

- текущий статус готовности
- readiness score
- good day probability
- краткое объяснение

Комментарий:

- readiness output уже реализован в backend
- history endpoint отдает последние daily points для trend UI

---

## 3. Daily usage (MVP)

### Flow

1. Пользователь открывает iOS app
2. `SyncCoordinator` запускает auto sync
3. Backend сохраняет payload и выполняет deterministic recompute
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

---

## 4. Scenario: After hard training block

### Context

- несколько дней высокой нагрузки
- накопленная усталость

### Expected system behavior

- снижение readiness
- снижение `good_day_probability`
- explanation через load + recovery breakdown

---

## 5. Scenario: After recovery

### Context

- период снижения нагрузки
- восстановление

### Expected system behavior

- рост readiness
- рост `good_day_probability`

---

## 6. Scenario: Stable training

### Context

- регулярные тренировки
- умеренная нагрузка

### Expected system behavior

- стабильный readiness
- стабильный readiness output без скрытой логики

---

## 7. Scenario: Load spike

### Context

- резкий рост нагрузки

### Expected system behavior

- корректировка readiness вниз
- корректировка probability вниз

---

## 8. Scenario: No recent data

### Context

- нет тренировок
- недостаточно данных

### Expected system behavior

- ограниченная уверенность
- fallback на доступные слои readiness

---

## 9. Scenario: Incomplete data

### Context

- отсутствуют некоторые метрики
- нет power / HR

### Expected system behavior

- использовать доступные данные
- не ломать модель
- явно ограничивать точность

---

## 10. Scenario: Long break

### Context

- длительный перерыв

### Expected system behavior

- формально возможен рост readiness за счет текущего baseline
- downstream decision layer должен учитывать это отдельно, когда будет реализован

---

## 11. System behavior expectations

Во всех сценариях система должна:

- быть предсказуемой
- быть объяснимой
- не давать противоречивые outputs между score, probability и status

---

## 12. Not in scope

Система пока не делает:

- долгосрочное планирование
- автоматическое построение тренировочных программ
- персонализированный coaching
- production-calibrated decision layer

---

## 13. Future scenarios

Планируется:

- адаптивные планы тренировок
- recommendation layer
- ride briefing layer
- прогнозирование результата
- интеграция с календарем

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
