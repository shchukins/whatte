from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Path as FastAPIPath, Query, Request
from fastapi.responses import RedirectResponse
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
from .presentation import physiology_error, today_label
from backend.services import user_profile_service as profile_service

router = APIRouter(prefix="/today", tags=["today"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)
templates.env.filters["today_label"] = today_label
FeedbackScore = Annotated[int, FastAPIPath(ge=1, le=5)]
RpeScore = Annotated[int, FastAPIPath(ge=1, le=10)]


def _reject_cross_site_request(request: Request) -> None:
    # Basic Auth protects the route at the edge. Sec-Fetch-Site adds a small,
    # deterministic CSRF boundary for state-changing native form submissions.
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="Отправка формы с другого сайта запрещена")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname != request.url.hostname:
        raise HTTPException(status_code=403, detail="Отправка формы с другого сайта запрещена")


def _redirect_to_today(*, saved: str, activity_id: int | None = None) -> RedirectResponse:
    location = f"/today?saved={saved}"
    if activity_id is not None:
        location += f"&activity_id={activity_id}"
    return RedirectResponse(location, status_code=303)


@router.get("")
@router.get("/")
def today_index(
    request: Request,
    activity_id: int | None = Query(default=None, ge=1),
    saved: str | None = Query(default=None),
):
    return _today_page(request, activity_id=activity_id, saved=saved)


def _today_page(
    request: Request,
    *,
    activity_id: int | None = None,
    saved: str | None = None,
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
            "saved": saved if saved in {"recovery", "rpe", "physiology"} else None,
            "physiology_values": physiology_values,
            "physiology_errors": physiology_errors or {},
            "physiology_clears": physiology_clears,
            "rpe_options": list(RPE_LABELS.items()),
            **asdict(data),
        },
    )


@router.post("/recovery/{score}")
def submit_recovery(request: Request, score: FeedbackScore):
    _reject_cross_site_request(request)
    target_date = today_service.get_local_today()
    upsert_next_day_recovery_feedback(
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
):
    _reject_cross_site_request(request)
    activity = today_service.get_today_activity(
        settings.daily_readiness_user_id,
        preferred_activity_id=activity_id,
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Подходящая тренировка не найдена")
    upsert_activity_rpe_v2(
        activity_id=activity_id,
        score=score,
        source=FEEDBACK_SOURCE_WEB,
    )
    return _redirect_to_today(saved="rpe", activity_id=activity_id)


def _profile_page(request: Request, *, message=None, error=None, status_code=200):
    return templates.TemplateResponse(
        request=request, name="today/profile.html",
        context={**profile_service.get_profile(settings.daily_readiness_user_id),
                 "message": message, "error": error}, status_code=status_code,
    )


@router.get("/profile")
def profile_page(request: Request, saved: bool = False):
    return _profile_page(request, message="Значение сохранено." if saved else None)


@router.post("/profile")
async def save_profile(request: Request):
    _reject_cross_site_request(request)
    # Native URL-encoded forms avoid adding a multipart parser dependency.
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Ожидается форма в формате URL-encoded')
    try:
        fields = parse_qs((await request.body()).decode('utf-8'), max_num_fields=3)
        if any(len(values) != 1 for values in fields.values()):
            raise ValueError('Duplicate form field')
        change = profile_service.ProfileChange.model_validate(
            {key: values[-1] for key, values in fields.items()}
        )
    except (ValidationError, ValueError):
        return await run_in_threadpool(_profile_page, request, error="Проверьте дату и значение: FTP 1–1000 Вт, HR max — целое число 1–250 уд/мин, вес 1–500 кг. Дата не может быть в будущем.", status_code=422)
    # Database work runs in FastAPI's thread pool, not on the event loop.
    await run_in_threadpool(profile_service.save_profile_value,
                            settings.daily_readiness_user_id, change)
    return RedirectResponse('/today/profile?saved=true', status_code=303)


@router.post("/profile/recompute")
def recompute_profile(request: Request):
    _reject_cross_site_request(request)
    try:
        count = profile_service.recompute_profile_history(settings.daily_readiness_user_id)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise
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
    try:
        fields = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True, max_num_fields=1 + 2 * len(VALUE_FIELDS),
        )
        allowed = {"local_date", *VALUE_FIELDS, *(f"clear_{name}" for name in VALUE_FIELDS)}
        if set(fields) - allowed or any(len(items) != 1 for items in fields.values()):
            raise ValueError("Unexpected or duplicate form field")
        values = {name: fields.get(name, [""])[0].strip() for name in VALUE_FIELDS}
        clears = {name for name in VALUE_FIELDS if fields.get(f"clear_{name}") == ["1"]}
        if any(fields.get(f"clear_{name}", ["1"]) != ["1"] for name in VALUE_FIELDS):
            raise ValueError("Invalid clear action")
        target_date = date.fromisoformat(fields.get("local_date", [""])[0])
        if target_date != today_service.get_local_today():
            return await run_in_threadpool(
                _today_page, request, physiology_errors={
                    "form": "Наступил новый день. Обновите страницу «Сегодня» перед сохранением.",
                }, status_code=409,
            )
        # Empty controls omit a value; only an explicit clear sends null. The
        # shared model owns every numeric bound and persistence owns revisions.
        submitted = {name: None if name in clears else value
                     for name, value in values.items() if value or name in clears}
        patch = ManualPhysiologyPatch(
            local_date=target_date, source="web", **submitted,
        )
    except ValueError as exc:
        errors = {"form": "Проверьте введённые значения и повторите попытку."}
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
