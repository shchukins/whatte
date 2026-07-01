from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PROCESS_STARTED_AT = datetime.now(MOSCOW_TZ)
MAX_DATABASE_ERROR_LENGTH = 300
MAX_INGEST_ERROR_LENGTH = 240
INGEST_JOBS_LIMIT = 10


@dataclass(frozen=True)
class DashboardSystemStatus:
    backend_status: str
    database_status: str
    database_error: str | None
    server_time_moscow: str
    process_started_at_moscow: str
    process_uptime_seconds: int


@dataclass(frozen=True)
class DashboardIngestJobRow:
    id: int
    status: str
    reason: str | None
    strava_activity_id: int | None
    scheduled_at_moscow: str
    finished_at_moscow: str
    last_error_short: str


@dataclass(frozen=True)
class DashboardIngestJobsStatus:
    status: str
    error: str | None
    jobs: list[DashboardIngestJobRow]
    failed_count: int | None
    pending_count: int | None


def _format_moscow_timestamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def _sanitize_database_error(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    if settings.database_url in message:
        message = message.replace(settings.database_url, "[redacted]")
    return message[:MAX_DATABASE_ERROR_LENGTH]


def _truncate_text(value: str | None, *, limit: int = MAX_INGEST_ERROR_LENGTH) -> str:
    text = (value or "").strip()
    if not text:
        return "—"
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _get_database_status() -> tuple[str, str | None]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return "ok", None
    except Exception as exc:
        return "error", _sanitize_database_error(exc)


def get_dashboard_ingest_jobs_status() -> DashboardIngestJobsStatus:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        count(*) filter (where status = 'pending') as pending_count,
                        count(*) filter (where status in ('failed', 'error')) as failed_count
                    from strava_activity_ingest_job;
                    """
                )
                counts_row = cur.fetchone() or (0, 0)

                cur.execute(
                    """
                    select
                        id,
                        status,
                        reason,
                        strava_activity_id,
                        scheduled_at,
                        finished_at,
                        last_error
                    from strava_activity_ingest_job
                    order by id desc
                    limit %s;
                    """,
                    (INGEST_JOBS_LIMIT,),
                )
                job_rows = cur.fetchall()

        jobs = [
            DashboardIngestJobRow(
                id=row[0],
                status=row[1],
                reason=row[2],
                strava_activity_id=row[3],
                scheduled_at_moscow=_format_moscow_timestamp(row[4]),
                finished_at_moscow=_format_moscow_timestamp(row[5]),
                last_error_short=_truncate_text(row[6]),
            )
            for row in job_rows
        ]

        return DashboardIngestJobsStatus(
            status="ok",
            error=None,
            jobs=jobs,
            pending_count=counts_row[0],
            failed_count=counts_row[1],
        )
    except Exception as exc:
        return DashboardIngestJobsStatus(
            status="error",
            error=_sanitize_database_error(exc),
            jobs=[],
            pending_count=None,
            failed_count=None,
        )


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
