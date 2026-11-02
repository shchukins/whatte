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


def editorial_decision_text(code: str) -> str:
    """Presentation copy omits storage identities; original evidence stays available."""
    from .training import decision_text

    prefix, _, value = code.partition(":")
    if prefix == "propose_move":
        parts = value.split(":")
        return f"Предлагается перенести занятие на {parts[1]}. Остальные занятия не меняются."
    if prefix == "propose_move_to_today":
        return "Заменяющее занятие предлагается выполнить сегодня вместо его исходного вхождения."
    if prefix == "session_day_unknown":
        return "Есть занятие без даты; оно не распределяется автоматически."
    if prefix == "plan_completion_unconfirmed":
        return "Связь записанной активности с планом не подтверждена."
    if prefix == "load_not_covered":
        return "Нагрузка записанной активности неизвестна или не поддерживается; она не считается нулевой."
    return decision_text(code)


def today_editorial(data, training: dict | None, error: str | None) -> dict:
    """Project existing facts/choices into one article, without ranking workouts.

    The local SSR date owns the week. A snapshot crossing midnight is disclosed
    and cannot expose old-day consent forms. Activity facts precede proposals;
    neither a matching duration nor an RPE value implies assignment fulfillment.
    """
    local_day = date.fromisoformat(data.today)
    current = bool(training and training["today"] == local_day)
    t = training if current else None
    facts = list(t.get("today_activities", [])) if t else []
    # Independent activity-section fallback survives a training-context read error.
    if not facts and data.activity and data.activity.local_date == data.today:
        facts = [dict(activity_id=str(data.activity.activity_id), local_date=local_day,
                      duration_s=None, duration_label=data.activity.duration,
                      activity_type=data.activity.sport_type, plan_link=None)]
    latest = next(iter(t.get("decisions", [])), None) if t else None
    original = t.get("target") if t else None
    option = t["decision"].recommendation if t and t.get("decision") else None
    if latest and (latest.get("choice") or latest.get("stale")):
        inputs = latest["input_json"]["context"]
        original = next((s for s in inputs["week_plan"] or ()
                         if s["id"] == inputs["today_session_id"]), original)
    view = dict(current=current, date_label=f"{WEEKDAYS[local_day.weekday()]}, {_calendar_label(local_day, show_year=True)}",
                facts=facts, latest=latest, original=original,
                option=option, can_choose=False, warnings=[], state="missing",
                status="Нужны данные", kicker="Обоснованного выбора пока нет",
                title="Сначала уточним сегодняшний день.",
                lead="Заполните недостающий контекст, чтобы получить обоснованное предложение.")
    if facts:
        view.update(state="recorded", status="Активность записана", kicker="Факт сегодняшнего дня",
                    title="Тренировка уже записана", lead="Факт тренировки сохранён. Новая тренировка автоматически не предлагается.", option=None)
    elif error or (training and not current):
        view.update(state="error", status="Контекст недоступен", title="Проверим данные перед решением.",
                    lead=error or "Наступил новый день. Обновите Сегодня перед изменением условий.", option=None)
    elif latest and latest.get("stale"):
        view.update(state="stale", status="Условия изменились", title="Проверьте решение заново.",
                    lead=(f"Вы ранее {'приняли' if latest['choice'] == 'accepted' else 'отклонили'} предложение. Контекст после ответа изменился; проверьте условия заново."
                          if latest.get("choice") else "Сохранённое предложение устарело. Получите новое перед подтверждением."), option=None)
    elif latest and latest.get("choice"):
        accepted = latest["choice"] == "accepted"
        view.update(state=latest["choice"], status="Ответ сохранён", kicker="Ваш выбор на сегодня",
                    title="Предложение принято" if accepted else "Предложение отклонено",
                    lead="Ваш выбор сохранён. Принятое предложение показано здесь." if accepted else "Отказ не означает отдых или выполнение занятия.",
                    option=latest["decision_json"]["recommendation"] if accepted else None)
    elif option:
        view.update(state="decision", status="Предложение готово",
                    kicker={"KEEP": "Выполнить по плану", "SHORTEN": "Сократить плановую длительную",
                            "SUBSTITUTE": "Заменить плановое занятие", "RESCHEDULE": "Предложить перенос",
                            "SKIP": "Пропустить сегодня"}[option.action],
                    title={"KEEP": "Сегодня — по плану.", "SHORTEN": "Сохраните ритм. Сократите объём.",
                           "SUBSTITUTE": "Сегодня — другое занятие.", "RESCHEDULE": "Сохраним занятие для другого дня.",
                           "SKIP": "Сегодня без тренировки."}[option.action],
                    lead=" ".join(editorial_decision_text(line) for line in option.reasons),
                    can_choose=bool(latest and latest["status"] == "proposed" and t.get("proposal_matches")))
    if t:
        if not t.get("target") and not t.get("targets") and not facts and not latest:
            view["lead"] = "На сегодня нет датированного занятия. Плановое решение не строится."
        if view["state"] == "missing":
            view["warnings"].extend(editorial_decision_text(code) for code in t.get("missing_context", ())
                                    if not code.startswith("future_window_unknown:"))
        if any(a["load"].included is not True for a in t["activities"]):
            view["warnings"].append("Нагрузка части записанных активностей неизвестна или не поддерживается. Она не считается нулевой.")
        view["warnings"].append("Полнота синхронизации Strava не подтверждена; локальная история может быть неполной.")
    if error and facts:
        view["warnings"].append(error)
    readiness = data.readiness
    if readiness and (str(readiness["date"]) != data.today or readiness.get("freshness_state") == "stale"):
        view["warnings"].append(f"Результат устарел. Рекомендация относится к {readiness['date']}; актуальная готовность на сегодня не подтверждена.")
    elif readiness and readiness.get("freshness_state") == "partial":
        view["warnings"].append("Данные готовности неполные; оценка не является разрешением тренировки.")
    view["warnings"] = list(dict.fromkeys(view["warnings"]))
    monday = local_day - timedelta(days=local_day.weekday())
    sessions = t["saved_context"].plan.sessions if t else None
    activities = list(t["activities"]) if t else []
    known_ids = {str(a["activity_id"]) for a in activities}
    activities.extend(a for a in facts if str(a["activity_id"]) not in known_ids)
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        planned = [s for s in sessions or () if s.day == day]
        actual = [a for a in activities if str(a.get("local_date")) == day.isoformat()]
        # Credit the linked assignment's date, not the activity's upload/date.
        fulfilled = [s for s in planned if any(a.get("plan_link") and
                     a["plan_link"]["session_id"] == s.id and
                     a["plan_link"]["correspondence"] == "fulfilled" for a in activities)]
        days.append(dict(date=day.isoformat(), weekday=WEEKDAYS[offset], number=day.day,
                         current=day == local_day, plan=planned, facts=actual,
                         fulfilled=fulfilled, plan_known=sessions is not None, facts_known=t is not None or bool(actual)))
    view["week"] = days
    return view
