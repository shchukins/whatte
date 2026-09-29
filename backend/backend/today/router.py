from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Path as FastAPIPath, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from backend.config import settings
from backend.services.rpe_service import RPE_LABELS
from backend.services.subjective_feedback_service import (
    FEEDBACK_SOURCE_WEB,
    upsert_activity_rpe_v2,
    upsert_next_day_recovery_feedback,
)

from . import service as today_service
from backend.services import user_profile_service as profile_service

router = APIRouter(prefix="/today", tags=["today"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)
FeedbackScore = Annotated[int, FastAPIPath(ge=1, le=5)]
RpeScore = Annotated[int, FastAPIPath(ge=1, le=10)]


def _reject_cross_site_request(request: Request) -> None:
    # Basic Auth protects the route at the edge. Sec-Fetch-Site adds a small,
    # deterministic CSRF boundary for state-changing native form submissions.
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="cross-site form submission rejected")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname != request.url.hostname:
        raise HTTPException(status_code=403, detail="cross-site form submission rejected")


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
    data = today_service.get_today_data(
        settings.daily_readiness_user_id,
        preferred_activity_id=activity_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="today/index.html",
        context={
            "page_title": "Whatte Today",
            "saved": saved if saved in {"recovery", "rpe"} else None,
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
        raise HTTPException(status_code=404, detail="eligible activity not found")
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
        raise HTTPException(415, 'Expected a URL-encoded form')
    try:
        fields = parse_qs((await request.body()).decode('utf-8'), max_num_fields=3)
        if any(len(values) != 1 for values in fields.values()):
            raise ValueError('Duplicate form field')
        change = profile_service.ProfileChange.model_validate(
            {key: values[-1] for key, values in fields.items()}
        )
    except (ValidationError, ValueError):
        return await run_in_threadpool(_profile_page, request, error="Проверьте дату и значение: FTP 1–1000 Вт, вес 1–500 кг. Дата не может быть в будущем.", status_code=422)
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
