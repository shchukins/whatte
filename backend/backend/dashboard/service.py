from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PROCESS_STARTED_AT = datetime.now(MOSCOW_TZ)
MAX_DATABASE_ERROR_LENGTH = 300


@dataclass(frozen=True)
class DashboardSystemStatus:
    backend_status: str
    database_status: str
    database_error: str | None
    server_time_moscow: str
    process_started_at_moscow: str
    process_uptime_seconds: int


def _format_moscow_timestamp(value: datetime) -> str:
    return value.astimezone(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def _sanitize_database_error(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    if settings.database_url in message:
        message = message.replace(settings.database_url, "[redacted]")
    return message[:MAX_DATABASE_ERROR_LENGTH]


def _get_database_status() -> tuple[str, str | None]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return "ok", None
    except Exception as exc:
        return "error", _sanitize_database_error(exc)


def get_dashboard_system_status() -> DashboardSystemStatus:
    now = datetime.now(MOSCOW_TZ)
    database_status, database_error = _get_database_status()
    uptime_seconds = max(0, int((now - PROCESS_STARTED_AT).total_seconds()))

    return DashboardSystemStatus(
        backend_status="ok",
        database_status=database_status,
        database_error=database_error,
        server_time_moscow=_format_moscow_timestamp(now),
        process_started_at_moscow=_format_moscow_timestamp(PROCESS_STARTED_AT),
        process_uptime_seconds=uptime_seconds,
    )
