"""Today delivery adapter. All feasibility and ranking stay in the existing policy."""
from urllib.parse import urlencode

from backend.services import training_context_service as store
from backend.services.training_decision_loop import evidence
from backend.services.training_decision_policy import ActionConstraints, TrainingDecisionContext

TYPES = {"long_z2": "Длительная Z2", "z2": "Z2", "intensity": "Интенсивная", "recovery": "Восстановительная"}
ACTIONS = {"KEEP": "Выполнить по плану", "SHORTEN": "Сократить", "SUBSTITUTE": "Заменить", "RESCHEDULE": "Предложить перенос", "SKIP": "Пропустить сегодня"}
REVIEW_FIELDS = {"decision_day", "session_id", "training_allowed", "intensity_allowed", "reviewed_window", "substitute"}


def review_inputs(fields, edit, today):
    """Permissions are explicit, date-scoped preview inputs, never persisted consent."""
    def one(key, default=""):
        values = fields.getlist(key)
        if len(values) > 1:
            raise ValueError("Повторяющееся поле")
        return values[0] if values else default

    day = one("decision_day")
    # An old bookmark cannot authorize training on a new local day.
    if day and day != str(today):
        return {}, ActionConstraints(), (), None
    if not day:
        return {}, ActionConstraints(), (), None
    permission = one("training_allowed")
    intensity = one("intensity_allowed")
    if permission not in ("", "yes", "no") or intensity not in ("", "yes", "no"):
        raise ValueError("Выберите допустимость тренировки")
    sessions = edit.plan.sessions or ()
    selected = one("session_id") or None
    if selected and not any(s.id == selected and s.day == today for s in sessions):
        raise ValueError("Выбранное занятие больше не запланировано на сегодня")
    reviews = tuple(fields.getlist("reviewed_window"))
    known = {str(w.day) for w in edit.plan.windows if w.day > today and w.confirmed and w.duration_minutes}
    if set(reviews) - known:
        raise ValueError("Окно переноса изменилось. Проверьте план")
    substitutes = tuple(fields.getlist("substitute"))
    if set(substitutes) - {s.id for s in sessions if s.day and s.day >= today}:
        raise ValueError("Занятие для замены изменилось. Проверьте план")
    form = dict(training_allowed=permission, intensity_allowed=intensity,
                session_id=selected, reviewed_window=reviews, substitute=substitutes)
    constraints = ActionConstraints(training_allowed={"yes": True, "no": False}.get(permission),
        intensity_allowed={"yes": True, "no": False}.get(intensity), substitute_session_ids=substitutes)
    return form, constraints, reviews, selected


def today_decision(user_id, fields):
    snapshot = store.get_policy_context(user_id)
    edit = snapshot['saved_context']
    today = snapshot['today']
    form, constraints, reviews, selected = review_inputs(fields, edit, today)
    decisions = snapshot.get('decisions', [])
    if not fields.get('decision_day') and decisions and decisions[0]['status'] == 'proposed':
        # Reload the saved proposal on a plain visit without inventing consent.
        saved = TrainingDecisionContext.model_validate(decisions[0]['input_json']['context'])
        constraints = saved.constraints
        selected = saved.today_session_id
        reviews = tuple(w.id for w in saved.future_windows or () if w.compatible_session_ids)
        form = dict(training_allowed={True: 'yes', False: 'no'}.get(constraints.training_allowed, ''),
                    intensity_allowed={True: 'yes', False: 'no'}.get(constraints.intensity_allowed, ''),
                    session_id=selected, reviewed_window=reviews, substitute=constraints.substitute_session_ids)
    result = store.assemble_policy_context(edit, snapshot['activities'], today=today,
        today_session_id=selected, constraints=constraints, reviewed_window_ids=reviews,
        physiology_available=bool(snapshot['context'] and snapshot['context'].physiology_available))
    targets = [s for s in edit.plan.sessions or () if s.day == today]
    target = next((s for s in targets if s.id == selected), targets[0] if len(targets) == 1 else None)
    window = next((w for w in edit.plan.windows if w.day == today), None)
    # A recorded workout takes priority over another unconfirmed prescription.
    today_activities = [a for a in result['activities'] if a.get('local_date') == today]
    completed_ids = {a['plan_link']['session_id'] for a in result['activities']
                     if a.get('plan_link') and a['plan_link']['correspondence'] == 'fulfilled'}
    return dict(**result, form=form, targets=targets, target=target,
        decisions=decisions, today_activities=today_activities, delivery=snapshot.get('delivery', {}),
        proposal_matches=bool(decisions and evidence(result) == decisions[0]['input_json']),
        link_targets=[s for s in edit.plan.sessions or () if s.day and s.day <= today and s.id not in completed_ids],
        primary=bool((targets and edit.block_priority) or today_activities or decisions),
        minutes=window.duration_minutes if window and window.confirmed else None,
        future_windows=[w for w in edit.plan.windows if w.day > today and w.confirmed and w.duration_minutes],
        substitutes=[s for s in edit.plan.sessions or () if s.day and s.day >= today and (not target or s.id != target.id)])


def preview_url(fields):
    values = [(key, value) for key in REVIEW_FIELDS for value in fields.getlist(key)]
    return '/today?' + urlencode(values) + '#training-decision'


COPY = {
    'original_plan_fits_available_time': 'Исходное занятие помещается в доступное время.',
    'preserve_partial_planned_stimulus_without_intensity_compensation': 'Сохраняем часть плановой аэробной работы без компенсации интенсивностью.',
    'unfinished_block_priority_session_explicitly_allowed_today': 'Невыполненное ключевое занятие соответствует приоритету блока и явно разрешено сегодня.',
    'confirmed_free_window_with_explicit_week_compatibility': 'Есть подтверждённое свободное окно с проверенной совместимостью с неделей.',
    'no_training_today_no_compensation_debt': 'Сегодня без тренировки. Долга по компенсации пропуска нет.',
    'other_sessions_unchanged_no_automatic_compensation': 'Остальные занятия остаются на месте. Автоматической компенсации нет.',
    'protect_full_unfinished_block_key_stimulus_before_partial_work': 'Приоритет — сохранить полный ключевой стимул блока; затем частичную работу.',
    'keep_fitting_plan_else_unfinished_block_key_before_supporting_work': 'Сохраняем выполнимый план; иначе ключевая работа блока важнее поддерживающей.',
    'training_today_prohibited_only_reviewed_move_or_skip': 'Сегодня тренировка запрещена: возможны только проверенный перенос или пропуск.',
    'today_session_already_completed_do_not_repeat': 'Занятие уже выполнено, повторять его не нужно.',
    'block_priority_unknown': 'Не задан приоритет блока.',
    'week_plan_unknown': 'Недельный план не задан.',
    'today_plan_unknown': 'Не выбрано запланированное занятие на сегодня.',
    'today_session_unknown_or_ambiguous': 'На сегодня нет занятия или нужно выбрать одно из нескольких.',
    'today_available_minutes_unconfirmed': 'Доступное время сегодня неизвестно.',
    'training_permission_unknown': 'Укажите, допустима ли тренировка сегодня.',
    'intensity_permission_unknown': 'Допустимость интенсивной работы не подтверждена.',
    'completed_work_unknown': 'История выполненной работы неизвестна.',
    'multiple_substitutes_no_preference': 'Есть несколько допустимых замен; оснований предпочесть одну недостаточно.',
    'no_admissible_action': 'Нет допустимого варианта при заданных ограничениях.',
    'future_windows_unknown_no_move_assumed': 'Будущая доступность неизвестна. Возможность переноса не предполагается.',
    'optional_physiology_unavailable_no_recovery_assumption': 'Физиологические данные отсутствуют; это не означает хорошее восстановление.',
    'strava_sync_completeness_unverified': 'Полнота синхронизации Strava не подтверждена; локальная история может быть неполной.',
    'plan_completion_not_linked': 'Выполнение назначения учитывается только после явного подтверждения связи с активностью.',
    'future_session_compatibility_unreviewed': 'Время в будущем само по себе не подтверждает совместимость переноса с неделей.',
}


def decision_text(code):
    """Translate contract codes for display only; retain unknown codes visibly."""
    if code in COPY:
        return COPY[code]
    prefix, _, rest = code.partition(':')
    if prefix == 'future_window_unknown':
        return f'Доступность {rest} неизвестна; перенос на этот день не предполагается.'
    if prefix == 'session_day_unknown':
        return f'У занятия {rest} не задан день; оно не распределяется автоматически.'
    if prefix == 'load_not_covered':
        return f'Нагрузка активности {rest.split(":")[0]} неизвестна или не поддерживается; она не считается нулевой.'
    if prefix == 'plan_completion_unconfirmed':
        return f'Активность {rest} не подтверждает выполнение занятия плана.'
    if prefix == 'pending_key_sessions':
        return f'Ключевых занятий без подтверждённого выполнения: {len(rest.split(",")) if rest else 0}.'
    if prefix == 'propose_move':
        parts = rest.split(':')
        return f'Предлагается перенести занятие {parts[0]} на {parts[1]}. План пока не изменён.'
    if prefix == 'propose_move_to_today':
        return f'Предлагается выполнить {rest.split(":")[0]} сегодня, убрав исходное вхождение. План пока не изменён.'
    if prefix in TYPES:
        if rest == 'partial':
            return f'{TYPES[prefix]}: частичная работа; полный плановый объём не сохраняется.'
        if rest.startswith('duration_reduced_by_'):
            return f'{TYPES[prefix]}: потеря {rest.removeprefix("duration_reduced_by_").removesuffix("_minutes")} мин планового объёма.'
        if rest == 'today_planned_session_omitted':
            return f'{TYPES[prefix]}: сегодняшнее плановое занятие пропускается.'
    return TYPES.get(code, code)
