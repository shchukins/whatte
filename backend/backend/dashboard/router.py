from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _build_dashboard_context(request: Request) -> dict[str, object]:
    server_time = datetime.now(MOSCOW_TZ)
    return {
        "request": request,
        "page_title": "Human Engine Internal Dashboard",
        "backend_status": "OK",
        "server_time": server_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "server_timezone": "Europe/Moscow",
    }


@router.get("")
@router.get("/")
async def dashboard_index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context=_build_dashboard_context(request),
    )
