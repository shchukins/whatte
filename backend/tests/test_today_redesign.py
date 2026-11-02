"""One editorial answer over the existing Task 4 snapshot; no inferred completion."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services import training_context_service as store
from backend.services.activity_load_service import ActivityLoadAssessment
from backend.services.training_decision_loop import evidence, apply_option
from backend.today import service, training
from backend.today.presentation import today_editorial

DAY = date(2026, 10, 29)


def example(state="decision"):
    """Fixed synthetic inputs; recommendations are produced by the real policy."""
    edit = store.TrainingContextEdit(block_priority="long_z2", plan=store.WeekPlan(
        week_start=store.week_start(DAY), sessions=(
            store.SavedSession(id="private-original-id", day=DAY, session_type="long_z2",
                               duration_minutes=120, minimum_shortened_minutes=45, priority="key"),
            store.SavedSession(id="support", day=DAY + timedelta(days=1), session_type="recovery",
                               duration_minutes=30, priority="supporting")),
        windows=(store.DailyWindow(day=DAY, duration_minutes=0 if state == "no-time" else 50,
                                  confirmed=state != "missing"),)))
    facts = []
    if state in ("recorded", "fulfilled", "different"):
        facts = [dict(activity_id="123", local_date=DAY, duration_s=3120, activity_type="Ride",
                      load=ActivityLoadAssessment(None, "unavailable_metrics_record"), rpe=None,
                      plan_link=None if state == "recorded" else dict(session_id="private-original-id",
                               correspondence="fulfilled" if state == "fulfilled" else "different"))]
    context = store.assemble_policy_context(edit, facts, today=DAY,
        constraints=training.ActionConstraints(training_allowed=None if state == "missing" else True))
    context.update(form=dict(training_allowed="" if state == "missing" else "yes"), targets=[edit.plan.sessions[0]],
                   target=edit.plan.sessions[0], today_activities=facts, decisions=[], delivery={},
                   proposal_matches=False, link_targets=[s for s in edit.plan.sessions if s.day <= DAY], primary=True,
                   minutes=None if state == "missing" else edit.plan.windows[0].duration_minutes,
                   future_windows=[], substitutes=[])
    if state in ("decision", "accepted", "declined", "stale"):
        choice = state if state in ("accepted", "declined") else None
        context["decisions"] = [dict(id=42, input_json=evidence(context),
            decision_json=context["decision"].model_dump(mode="json"), choice=choice,
            stale=state == "stale", status=choice or ("stale" if state == "stale" else "proposed"))]
        context["proposal_matches"] = state != "stale"
        if state == "accepted":
            plan = apply_option(edit, context["context"], context["decision"].recommendation)
            accepted = edit.model_copy(update={"plan": plan, "revision": 1})
            context.update(store.assemble_policy_context(accepted, facts, today=DAY))
            context.update(target=plan.sessions[0], targets=[plan.sessions[0]], link_targets=[s for s in plan.sessions if s.day <= DAY])
    section = service.TodaySection("ok", None)
    readiness = dict(date=str(DAY - timedelta(days=1) if state == "missing" else DAY),
                     readiness_score=68.0, status_text="Хорошая готовность", recommendation="moderate",
                     freshness_state="stale" if state == "missing" else "fresh",
                     readiness_computed_at="2026-10-29T04:10:00Z", briefing_text="Сохранённая сводка.")
    activity = service.TodayActivity(123, "Утренняя поездка", "Ride", "29.10, 08:20", "23.5 км", "52 мин",
                                     None, None, local_date=str(DAY)) if facts else None
    data = service.TodayData("athlete", str(DAY), readiness, section, [],
        service.TodayFeedback(4, "fresh", "07:00"), section, activity, section, [], section)
    return data, context


@pytest.mark.parametrize("state", ["decision", "missing", "recorded", "no-time", "accepted", "declined", "stale", "fulfilled", "different"])
def test_single_answer_native_controls_and_read_only_render(monkeypatch, state):
    data, context = example(state)
    before = deepcopy(context)
    monkeypatch.setattr(service, "get_today_data", lambda *a, **kw: data)
    monkeypatch.setattr(training, "today_decision", lambda *a, **kw: context)
    client = TestClient(app)
    page = client.get("/today")
    assert page.status_code == 200
    assert page.text.count("<h1 ") == 1
    assert page.text.count('class="week-date"') == 7
    assert page.headers["cache-control"] == "no-store"
    assert context == before
    assert client.get("/today").text == page.text
    assert 'id="readiness-title"' in page.text
    assert '<h1 id="readiness-title"' not in page.text
    if state in ("recorded", "fulfilled", "different"):
        assert 'data-state="recorded"' in page.text
        assert 'action="/today/training-choice"' not in page.text
        assert 'action="/today/training-decision"' not in page.text
        assert 'href="/today?activity_id=123#rpe"' in page.text
        if state == "recorded":
            assert 'action="/today/training-completion"' in page.text
            assert 'value="fulfilled"' in page.text and 'value="different"' in page.text
        else:
            assert 'action="/today/training-completion"' not in page.text
        if state == "different":
            assert "выполнение не засчитано" in page.text
            assert "✓ 1 подтв." not in page.text
    elif state == "decision":
        assert 'action="/today/training-choice"' in page.text
        assert 'name="decision_id" value="42"' in page.text
    elif state in ("accepted", "declined", "stale"):
        assert 'action="/today/training-choice"' not in page.text
        assert 'action="/today/training-decision"' in page.text
    if state == "missing":
        assert 'value="" selected>Пока неизвестно' in page.text
        assert 'Доступное время сегодня неизвестно' in page.text
        assert page.text.index("Результат устарел.") < page.text.index('<details class="readiness-explanation">')


def test_preview_does_not_expose_consent_for_a_different_stored_proposal(monkeypatch):
    data, context = example()
    context["proposal_matches"] = False
    monkeypatch.setattr(service, "get_today_data", lambda *a, **kw: data)
    monkeypatch.setattr(training, "today_decision", lambda *a, **kw: context)
    page = TestClient(app).get("/today").text
    assert 'action="/today/training-choice"' not in page
    assert 'action="/today/training-decision"' in page


@pytest.mark.parametrize("day", [date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 3), date(2027, 1, 4)])
def test_week_is_local_monday_sunday_and_missing_is_not_rest(day):
    data, _ = example()
    screen = today_editorial(replace(data, today=str(day)), None, "offline")
    dates = [date.fromisoformat(d["date"]) for d in screen["week"]]
    assert dates[0].weekday() == 0 and dates[-1].weekday() == 6
    assert dates == [day - timedelta(days=day.weekday()) + timedelta(days=i) for i in range(7)]
    assert sum(d["current"] for d in screen["week"]) == 1
    assert all(not d["plan_known"] and not d["facts_known"] for d in screen["week"])


def test_credit_belongs_to_assignment_date_and_different_is_not_fulfillment():
    data, context = example("fulfilled")
    edit = context["saved_context"]
    earlier = edit.plan.sessions[0].model_copy(update={"day": DAY - timedelta(days=1)})
    plan = edit.plan.model_copy(update={"sessions": (earlier, *edit.plan.sessions[1:])})
    context["saved_context"] = edit.model_copy(update={"plan": plan})
    screen = today_editorial(data, context, None)
    wednesday, thursday = screen["week"][2:4]
    assert len(wednesday["fulfilled"]) == 1 and not wednesday["facts"]
    assert thursday["facts"] and not thursday["fulfilled"]
    context["activities"][0]["plan_link"]["correspondence"] = "different"
    assert not any(d["fulfilled"] for d in today_editorial(data, context, None)["week"])


def test_midnight_disables_old_snapshot_forms_and_keeps_independent_fact(monkeypatch):
    data, context = example()
    tomorrow = replace(data, today=str(DAY + timedelta(days=1)))
    screen = today_editorial(tomorrow, context, None)
    assert screen["state"] == "error" and not screen["current"] and not screen["can_choose"]
    assert "новый день" in screen["lead"]
    data, _ = example("recorded")
    screen = today_editorial(data, None, "Тренировочный контекст недоступен")
    assert screen["state"] == "recorded"
    assert "Тренировочный контекст недоступен" in screen["warnings"]


def test_saved_choice_after_context_change_is_historical_and_cannot_be_answered():
    data, context = example("accepted")
    context["decisions"][0]["stale"] = True
    screen = today_editorial(data, context, None)
    assert screen["state"] == "stale" and not screen["can_choose"]
    assert "ранее приняли" in screen["lead"]
    assert screen["original"]["duration_minutes"] == 120


def test_preview_original_is_the_selected_assignment_not_an_unrelated_proposal():
    data, context = example()
    context["target"] = context["saved_context"].plan.sessions[1]
    context["proposal_matches"] = False
    screen = today_editorial(data, context, None)
    assert screen["original"].id == "support"
    assert not screen["can_choose"]


def test_missing_plan_main_action_edits_the_plan(monkeypatch):
    data, context = example("missing")
    context["targets"] = []
    context["target"] = None
    monkeypatch.setattr(service, "get_today_data", lambda *a, **kw: data)
    monkeypatch.setattr(training, "today_decision", lambda *a, **kw: context)
    page = TestClient(app).get("/today").text
    assert 'id="primary-action" class="story-primary plan-action" href="/today/plan"' in page
    assert page.count('id="primary-action"') == 1


def test_independent_fact_survives_in_week_without_fabricating_other_days():
    data, _ = example("recorded")
    screen = today_editorial(data, None, "Контекст недоступен")
    assert len(screen["week"][3]["facts"]) == 1
    assert screen["week"][3]["facts_known"]
    assert not screen["week"][2]["facts_known"]
    assert not any(day["plan_known"] for day in screen["week"])
    assert screen["facts"][0]["duration_label"] == "52 мин"
