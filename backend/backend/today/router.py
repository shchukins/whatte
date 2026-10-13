from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Path as FastAPIPath, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from backend.config import settings
from backend.services.manual_physiology_service import (
    VALUE_FIELDS,
    ManualPhysiologyPatch,
    save_manual_physiology_observation,
)
from backend.services.rpe_service import RPE_LABELS
from backend.services.subjective_feedback_service import (
    FEEDBACK_SOURCE_WEB,
    upsert_activity_rpe_v2,
    upsert_next_day_recovery_feedback,
)

from . import service as today_service
from .history_service import get_diary_data
from .presentation import (
    diary_date_label, diary_week_label, diary_week_start, physiology_error, today_label,
)
from backend.services import user_profile_service as profile_service

router = APIRouter(prefix="/today", tags=["today"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)
templates.env.filters["today_label"] = today_label
templates.env.filters["diary_date"] = diary_date_label
templates.env.filters["diary_week_start"] = diary_week_start
templates.env.filters["diary_week"] = diary_week_label
templates.env.filters["today_timestamp"] = today_service.format_readiness_timestamp
FeedbackScore = Annotated[int, FastAPIPath(ge=1, le=5)]
RpeScore = Annotated[int, FastAPIPath(ge=1, le=10)]
RECOVERY_FORM_MAX_BYTES = 128


def _reject_cross_site_request(request: Request) -> None:
    # Basic Auth protects the route at the edge. Sec-Fetch-Site adds a small,
    # deterministic CSRF boundary for state-changing native form submissions.
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="Отправка формы с другого сайта запрещена")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname != request.url.hostname:
        raise HTTPException(status_code=403, detail="Отправка формы с другого сайта запрещена")


def _redirect_to_today(*, saved: str, activity_id: int | None = None, return_day: str | None = None) -> RedirectResponse:
    location = f"/today?saved={saved}"
    if activity_id is not None:
        location += f"&activity_id={activity_id}"
    if return_day is not None:
        location += f"&return_day={return_day}"
    if saved in {"recovery", "rpe"}:
        location += f"#{saved}"
    return RedirectResponse(location, status_code=303)


def _validated_return_day(raw: str | None, activity: today_service.TodayActivity | None) -> str | None:
    # Only an ISO day in the visible diary window matching the owned activity
    # can become a fixed internal link; never accept a URL or arbitrary anchor.
    if not raw or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        return None
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    today = today_service.get_local_today()
    if activity and activity.local_date == raw and today - timedelta(days=13) <= day <= today:
        return raw
    return None


@router.get("")
@router.get("/")
def today_index(
    request: Request,
    activity_id: int | None = Query(default=None, ge=1),
    saved: str | None = Query(default=None),
    return_day: str | None = Query(default=None),
):
    return _today_page(request, activity_id=activity_id, saved=saved, return_day=return_day)


@router.get("/history")
def history_page(request: Request, rpe: str = Query(default="all")):
    if rpe not in {"all", "missing"}:
        raise HTTPException(status_code=422, detail="Неизвестный фильтр RPE")
    data = get_diary_data(settings.daily_readiness_user_id, today_service.get_local_today())
    missing_count = None
    visible_activities = {}
    if data.activity_section.status == "ok":
        missing_count = sum(
            activity.rpe_score is None
            for day in data.days for activity in day.activities or []
        )
    for day in data.days:
        visible_activities[day.date] = [
            activity for activity in day.activities or []
            if rpe == "all" or activity.rpe_score is None
        ]
    return templates.TemplateResponse(
        request=request, name="today/history.html",
        context={"today": data.target_date, "diary": data, "rpe_filter": rpe,
                 "missing_rpe_count": missing_count, "visible_activities": visible_activities},
    )


@router.get("/context")
def local_day_context():
    # Lifecycle checks read only the server clock, never athlete data or state.
    return JSONResponse(
        {"local_date": today_service.get_local_today().isoformat(),
         "timezone": settings.whatte_timezone},
        headers={"Cache-Control": "no-store"},
    )


def _today_page(
    request: Request,
    *,
    activity_id: int | None = None,
    saved: str | None = None,
    return_day: str | None = None,
    rpe_error: str | None = None,
    recovery_error: str | None = None,
    physiology_values: dict[str, str] | None = None,
    physiology_errors: dict[str, str] | None = None,
    physiology_clears: set[str] | tuple[str, ...] = (),
    status_code: int = 200,
):
    data = today_service.get_today_data(
        settings.daily_readiness_user_id,
        preferred_activity_id=activity_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="today/index.html",
        status_code=status_code,
        context={
            "page_title": "Сегодня · Whatte",
            "selected_activity": activity_id is not None,
            "return_day": _validated_return_day(return_day, data.activity),
            "rpe_error": rpe_error,
            "recovery_error": recovery_error,
            "saved": saved if saved in {"recovery", "rpe", "physiology"} else None,
            "physiology_values": physiology_values,
            "physiology_errors": physiology_errors or {},
            "physiology_clears": physiology_clears,
            "rpe_options": list(RPE_LABELS.items()),
            **asdict(data),
        },
    )


@router.post("/recovery/{score}")
async def submit_recovery(request: Request, score: FeedbackScore):
    _reject_cross_site_request(request)
    try:
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise ValueError("Expected URL-encoded form")
        # One ISO date is sufficient; bound the body before decoding/parsing.
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > RECOVERY_FORM_MAX_BYTES:
                raise ValueError("Recovery form too large")
            body.extend(chunk)
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=1)
        raw_date = fields.get("local_date", [""])[0]
        if set(fields) != {"local_date"} or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date):
            raise ValueError("Expected one ISO local date")
        target_date = date.fromisoformat(raw_date)
    except ValueError:
        return await run_in_threadpool(
            _today_page, request, status_code=422,
            recovery_error="Самочувствие не сохранено: дата формы недействительна. Обновите страницу «Сегодня» перед отправкой.",
        )
    if target_date != today_service.get_local_today():
        return await run_in_threadpool(
            _today_page, request, status_code=409,
            recovery_error="Самочувствие не сохранено: дата формы устарела. Обновите страницу «Сегодня» перед отправкой.",
        )
    await run_in_threadpool(
        upsert_next_day_recovery_feedback,
        user_id=settings.daily_readiness_user_id,
        target_date=target_date,
        score=score,
        source=FEEDBACK_SOURCE_WEB,
    )
    return _redirect_to_today(saved="recovery")


@router.post("/rpe/{activity_id}/{score}")
def submit_rpe(
    request: Request,
    activity_id: Annotated[int, FastAPIPath(ge=1)],
    score: RpeScore,
    return_day: str | None = Query(default=None),
):
    _reject_cross_site_request(request)
    activity = today_service.get_today_activity(
        settings.daily_readiness_user_id,
        preferred_activity_id=activity_id,
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Подходящая тренировка не найдена")
    return_day = _validated_return_day(return_day, activity)
    try:
        upsert_activity_rpe_v2(
            activity_id=activity_id, score=score, source=FEEDBACK_SOURCE_WEB,
        )
    except Exception:
        logging.getLogger(__name__).exception("today_rpe_save_failed")
        return _today_page(
            request, activity_id=activity_id, return_day=return_day, status_code=503,
            rpe_error="Не удалось сохранить RPE. Проверьте сохранённое состояние и повторите отправку.",
        )
    return _redirect_to_today(saved="rpe", activity_id=activity_id, return_day=return_day)


PROFILE_LABELS = {"ftp": "FTP", "hr_max": "HR max", "weight": "Вес"}
PROFILE_FIELD_ERRORS = {
    "metric": "Выберите FTP, HR max или вес.",
    "value": "Введите число: FTP 1–1000 Вт, HR max — целое 1–250 уд/мин, вес 1–500 кг.",
    "effective_from": "Введите дату в формате ГГГГ-ММ-ДД, не позднее сегодня.",
}


def _profile_page(request: Request, *, message=None, error=None, status_code=200,
                  metric="ftp", form=None, field_errors=None):
    profile = profile_service.get_profile(settings.daily_readiness_user_id)
    selected = metric if metric in PROFILE_LABELS else "ftp"
    current = profile["current"].get(selected)
    initial = {"metric": selected,
               "value": format(current["value"], "g") if current else "",
               "effective_from": str(profile["today"])}
    return templates.TemplateResponse(
        request=request, name="today/profile.html",
        context={**profile, "message": message, "error": error,
                 "form": initial if form is None else form,
                 "field_errors": field_errors or {}}, status_code=status_code,
    )


@router.get("/profile")
def profile_page(request: Request, saved: bool = False, metric: str = "ftp",
                 effective_from: date | None = None):
    message = "Значение сохранено." if saved else None
    if saved and metric in PROFILE_LABELS and effective_from is not None:
        message = f"{PROFILE_LABELS[metric]} сохранён с {effective_from}."
        if metric in ("ftp", "hr_max"):
            message += " Сохранение не выполняет пересчёт; проверьте раздел расчётов ниже."
    return _profile_page(request, message=message, metric=metric)


@router.post("/profile")
async def save_profile(request: Request):
    _reject_cross_site_request(request)
    # Native URL-encoded forms avoid adding a multipart parser dependency.
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Ожидается форма в формате URL-encoded')
    form = {}
    change = None
    field_errors = {}
    try:
        fields = parse_qs((await request.body()).decode('utf-8'),
                          max_num_fields=3, keep_blank_values=True)
        form = {key: values[-1] for key, values in fields.items()}
        if any(len(values) != 1 for values in fields.values()):
            raise ValueError('Duplicate form field')
        change = profile_service.ProfileChange.model_validate(form)
    except ValidationError as exc:
        for item in exc.errors():
            field = item["loc"][0] if item["loc"] else (
                "effective_from" if "Future effective dates" in str(item.get("ctx", {}).get("error", ""))
                else "value")
            if field in PROFILE_FIELD_ERRORS:
                field_errors[field] = PROFILE_FIELD_ERRORS[field]
    except ValueError:
        pass
    if change is None:
        return await run_in_threadpool(
            _profile_page, request, form=form, field_errors=field_errors,
            error="Значение не сохранено. Проверьте поля формы.", status_code=422)
    # Database work runs in FastAPI's thread pool, not on the event loop.
    try:
        await run_in_threadpool(profile_service.save_profile_value,
                                settings.daily_readiness_user_id, change)
    except Exception as exc:
        if isinstance(exc, HTTPException) and exc.status_code != 409:
            raise
        logging.getLogger(__name__).exception('profile_save_failed')
        return await run_in_threadpool(
            _profile_page, request, form=form,
            error="Значение не сохранено. Повторите сохранение; ваш ввод сохранён в форме.",
            status_code=409 if isinstance(exc, HTTPException) else 503)
    return RedirectResponse(
        f'/today/profile?saved=true&metric={change.metric}&effective_from={change.effective_from}',
        status_code=303)


@router.post("/profile/recompute")
def recompute_profile(request: Request):
    _reject_cross_site_request(request)
    try:
        count = profile_service.recompute_profile_history(settings.daily_readiness_user_id)
    except HTTPException as exc:
        if exc.status_code == 409:
            return _profile_page(request, error="Изменение профиля или пересчёт уже выполняется. Повторите пересчёт позже.", status_code=409)
        logging.getLogger(__name__).exception('profile_recompute_failed')
        return _profile_page(request, error="Пересчёт не завершён. Часть данных могла обновиться. Повторите пересчёт; отметка о необходимости пересчёта сохранена.", status_code=503)
    except Exception:
        logging.getLogger(__name__).exception('profile_recompute_failed')
        return _profile_page(request, error="Пересчёт не завершён. Часть данных могла обновиться. Повторите пересчёт; отметка о необходимости пересчёта сохранена.", status_code=503)
    return _profile_page(request, message=f"Пересчёт завершён. Обработано тренировок: {count}.")


@router.post("/physiology")
async def submit_physiology(request: Request):
    _reject_cross_site_request(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Ожидается форма в формате URL-encoded")
    values = {}
    clears = set()
    errors = {}
    form_value_fields = (
        *(name for name in VALUE_FIELDS if name != "sleep_duration_minutes"),
        "sleep_hours", "sleep_minutes",
    )
    try:
        fields = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True, max_num_fields=1 + len(form_value_fields) + len(VALUE_FIELDS),
        )
        allowed = {"local_date", *form_value_fields, *(f"clear_{name}" for name in VALUE_FIELDS)}
        if set(fields) - allowed or any(len(items) != 1 for items in fields.values()):
            raise ValueError("Unexpected or duplicate form field")
        values = {name: fields.get(name, [""])[0].strip() for name in form_value_fields}
        clears = {name for name in VALUE_FIELDS if fields.get(f"clear_{name}") == ["1"]}
        if any(fields.get(f"clear_{name}", ["1"]) != ["1"] for name in VALUE_FIELDS):
            raise ValueError("Invalid clear action")
        target_date = date.fromisoformat(fields.get("local_date", [""])[0])
        if target_date != today_service.get_local_today():
            return await run_in_threadpool(
                _today_page, request, physiology_values=values, physiology_clears=clears,
                physiology_errors={
                    "form": "Наступил новый день. Обновите страницу «Сегодня» перед сохранением.",
                }, status_code=409,
            )
        # Empty controls omit a value; only an explicit clear sends null. The
        # shared model owns every numeric bound and persistence owns revisions.
        submitted = {name: None if name in clears else value
                     for name, value in values.items() if value or name in clears}
        # Convert only in this web adapter. Blank parts omit sleep altogether;
        # an explicit clear wins, including over an invalid typed value.
        hours, minutes = values["sleep_hours"], values["sleep_minutes"]
        if "sleep_duration_minutes" in clears:
            submitted["sleep_duration_minutes"] = None
        elif hours or minutes:
            for name, maximum in (("sleep_hours", 24), ("sleep_minutes", 59)):
                value = values[name]
                if value and (not re.fullmatch(r"[0-9]+", value)
                              or len(value.lstrip("0")) > len(str(maximum))
                              or int(value.lstrip("0") or "0") > maximum):
                    errors[name] = f"Введите целое число от 0 до {maximum}."
            if not errors:
                duration = int(hours.lstrip("0") or "0") * 60 + int(minutes.lstrip("0") or "0")
                if duration > 1440:
                    errors["sleep_hours"] = "24 часа допустимы только с 0 минутами."
                    errors["sleep_minutes"] = errors["sleep_hours"]
                else:
                    submitted["sleep_duration_minutes"] = duration
        submitted.pop("sleep_hours", None)
        submitted.pop("sleep_minutes", None)
        if errors:
            raise ValueError("Invalid sleep parts")
        patch = ManualPhysiologyPatch(
            local_date=target_date, source="web", **submitted,
        )
    except ValueError as exc:
        errors["form"] = "Проверьте введённые значения и повторите попытку."
        if isinstance(exc, ValidationError):
            errors.update({str(error["loc"][0]): physiology_error(error) for error in exc.errors()})
        return await run_in_threadpool(
            _today_page, request, physiology_values=values,
            physiology_errors=errors, physiology_clears=clears, status_code=422,
        )
    if not submitted:
        return await run_in_threadpool(
            _today_page, request, physiology_values=values,
            physiology_errors={"form": "Введите значение или отметьте «Очистить» перед сохранением."},
            status_code=422,
        )
    try:
        await run_in_threadpool(
            save_manual_physiology_observation,
            user_id=settings.daily_readiness_user_id, patch=patch,
        )
    except Exception:
        logging.getLogger(__name__).exception("today_physiology_save_failed")
        return await run_in_threadpool(
            _today_page, request, physiology_values=values,
            physiology_errors={"form": "Не удалось сохранить наблюдения. Повторите попытку."},
            physiology_clears=clears, status_code=503,
        )
    return _redirect_to_today(saved="physiology")
