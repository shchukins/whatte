📄 READINESS_TODAY_SCREEN.md

1. Назначение

Экран Today / Readiness показывает текущее состояние пользователя и объясняет, насколько он готов к нагрузке сегодня и почему система пришла к этому выводу.

Экран должен давать быстрый, понятный и объяснимый ответ без необходимости анализа сырых данных.

⸻

2. Пользовательский сценарий

Основной сценарий (утро)

Пользователь открывает приложение и хочет за 5–10 секунд понять:
	1.	в каком он состоянии сегодня
	2.	хороший ли это день для тренировки
	3.	что именно повлияло на это состояние

⸻

3. Основной принцип UX

Один экран — один ответ:
“Насколько я готов сегодня и почему”

Правила:
	•	минимум элементов
	•	никакой перегрузки цифрами
	•	сначала смысл, потом детали
	•	объяснимость важнее точности

⸻

4. Структура экрана

4.1 Hero блок (главный)

Показывает итоговое состояние.

Состав:
	•	readiness_score (0–100)
	•	status_text
	•	good_day_probability

Пример:

59
Нормальная готовность
Вероятность хорошего дня: 60%


⸻

4.2 Why блок (объяснение)

Отвечает на вопрос: почему такой readiness

Верхний уровень
	•	Freshness
	•	Recovery

Пример:

Свежесть: +3.6
Восстановление: 68.8


⸻

4.3 Recovery breakdown

Берется из recovery_explanation_json.

Показываем:
	•	Sleep score
	•	HRV score
	•	Resting HR score

Пример:

Сон: 92
HRV: 64
Пульс покоя: 51

Важно:
	•	это не raw значения, а уже интерпретированные scores

⸻

4.4 Тренд (минимальный)

Простой контекст без перегрузки:
	•	readiness за последние 5–7 дней

Варианты:
	•	мини-график
	•	или список значений

⸻

4.5 Recommendation блок

В текущем backend уже доступен deterministic decision output:
	•	recommendation
	•	reason
	•	briefing / briefing_text

Это уже часть MVP data contract, а не future-only идея.

Пример:

Recommendation: endurance
Briefing: Сегодня нормальная готовность. Рекомендуется спокойная аэробная тренировка.

⸻

4.6 Короткое объяснение (опционально)

1–2 строки интерпретации.

Примеры:
	•	“Сон хороший, но HRV ниже baseline”
	•	“Свежесть растет после последних дней отдыха”
	•	“Нагрузка снижается, восстановление стабилизируется”

Это можно генерировать позже (не обязательно в MVP).

⸻

5. Логика отображения

5.1 Readiness

Источник:
	•	readiness_daily.readiness_score
	•	status_text
	•	good_day_probability

⸻

5.2 Freshness

Источник:
	•	load_state_daily_v2.freshness

Преобразование:
	•	freshness_norm = 50 + freshness

Отображение:
	•	можно показывать как число или как qualitative label

⸻

5.3 Recovery

Источник:
	•	health_recovery_daily.recovery_score_simple

⸻

5.4 Recovery breakdown

Источник:
	•	health_recovery_daily.recovery_explanation_json

Поля:
	•	sleep_score
	•	hrv_score
	•	rhr_score

⸻

6. Ограничения MVP

В первой версии не делаем:
	•	сложные графики
	•	baseline как отдельные метрики
	•	планирование
	•	сравнение с другими днями (кроме простого тренда)
	•	пользовательские настройки

Важно:
	•	baseline recommendation и briefing уже есть
	•	не реализованы более широкие planning features: duration suggestion, calendar-aware timing, workout construction

⸻

7. Критерии качества

Экран считается успешным, если пользователь:
	•	за 5 секунд понимает свое состояние
	•	видит, что влияет на readiness
	•	доверяет системе (есть объяснение)

⸻

8. Связь с backend

Экран использует:

Основные endpoints

GET /api/v1/model/readiness-daily/{user_id}/latest

или

GET /api/v1/model/readiness-daily/{user_id}/{date}

Данные внутри:
	•	readiness_score
	•	good_day_probability
	•	status_text
	•	recommendation
	•	reason
	•	briefing
	•	data_quality
	•	explanation_json:
	•	freshness
	•	freshness_norm
	•	recovery_score_simple
	•	recovery_explanation

⸻

9. Следующие шаги (после MVP)

После реализации базового экрана:

1. Trend UI
	•	нормальный график

2. История
	•	экран истории readiness

3. Более широкий planning layer
	•	duration / timing / context-aware guidance

4. Адаптивные подсказки
	•	объяснения уровня “инсайтов” без нарушения deterministic core
