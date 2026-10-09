"""Russian labels for Web Today only; codes and domain results stay intact."""

LABELS = {
    "recommendation": {
        "recovery": "Восстановление", "endurance": "Спокойная аэробная тренировка",
        "moderate": "Умеренная аэробная тренировка", "high_intensity": "Высокая интенсивность",
        "insufficient_data": "Недостаточно данных",
    },
    "status": {label: label for label in (
        "Высокая усталость", "Нагрузка", "Нормальная готовность",
        "Хорошая готовность", "Очень свежий",
    )},
    "freshness": {"fresh": "Актуальны", "partial": "Неполные", "stale": "Устарели", "missing": "Нет данных"},
    "availability": {"available": "Доступно", "unavailable": "Нет данных"},
    "factor": {"freshness": "Свежесть", "feeling": "Самочувствие", "physiology": "Физиология",
               "response": "Отклик на тренировку", "load": "Тренировочная нагрузка"},
    "source": {"web": "Web", "telegram": "Telegram", "import": "Импорт", "strava": "Strava"},
    "recovery": {"exhausted": "Без сил", "tired": "Усталость", "okay": "Нормально",
                 "fresh": "Бодро", "very_fresh": "Полон сил"},
    "rpe": {"Very easy": "Очень легко", "Easy": "Легко", "Light": "Лёгкая нагрузка",
            "Comfortable": "Комфортно", "Moderate": "Умеренно", "Steady": "Ровная нагрузка",
            "Hard": "Тяжело", "Very hard": "Очень тяжело",
            "Extremely hard": "Крайне тяжело", "Maximal": "Максимально"},
}


def today_label(code: str | None, kind: str) -> str:
    # Unknown values never imply a training decision or a normal data state.
    return LABELS.get(kind, {}).get(code, "Неизвестное состояние")


def physiology_error(error: dict) -> str:
    """Translate structured validation types without parsing Pydantic prose."""
    messages = {
        "greater_than": "Значение должно быть больше {gt}.",
        "greater_than_equal": "Значение должно быть не меньше {ge}.",
        "less_than_equal": "Значение должно быть не больше {le}.",
        "int_from_float": "Введите целое число.", "int_parsing": "Введите целое число.",
        "float_parsing": "Введите число.", "finite_number": "Введите конечное число.",
    }
    return messages.get(error["type"], "Проверьте значение.").format(**error.get("ctx", {}))
