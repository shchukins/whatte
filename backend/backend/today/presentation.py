"""Russian labels for Web Today only; codes and domain results stay intact."""

from datetime import date, timedelta


WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _calendar_label(day: date, *, show_year: bool) -> str:
    label = f"{day.day} {MONTHS[day.month - 1]}"
    return f"{label} {day.year}" if show_year else label


def diary_date_label(value: str, target_date: str) -> str:
    """Use the backend local target day, never browser time or host locale."""
    day, target = date.fromisoformat(value), date.fromisoformat(target_date)
    if day == target:
        return "Сегодня"
    if day == target - timedelta(days=1):
        return "Вчера"
    return f"{WEEKDAYS[day.weekday()]}, {_calendar_label(day, show_year=day.year != target.year)}"


def diary_week_start(value: str) -> str:
    day = date.fromisoformat(value)
    return (day - timedelta(days=day.weekday())).isoformat()


def diary_week_label(value: str, target_date: str) -> str:
    """Label the full Monday–Sunday week, including partial visible weeks."""
    start = date.fromisoformat(diary_week_start(value))
    end = start + timedelta(days=6)
    target = date.fromisoformat(target_date)
    show_year = start.year != end.year or start.year != target.year
    return f"Пн–Вс · {_calendar_label(start, show_year=show_year)} — {_calendar_label(end, show_year=show_year)}"


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
