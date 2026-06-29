from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from . import service as dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _build_dashboard_context(request: Request) -> dict[str, object]:
    return {
        "request": request,
        "page_title": "Human Engine Internal Dashboard",
        "system": asdict(dashboard_service.get_dashboard_system_status()),
    }


@router.get("")
@router.get("/")
async def dashboard_index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context=_build_dashboard_context(request),
    )
