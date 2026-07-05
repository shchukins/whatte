from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PROCESS_STARTED_AT = datetime.now(MOSCOW_TZ)
MAX_DATABASE_ERROR_LENGTH = 300
MAX_INGEST_ERROR_LENGTH = 240
MAX_STRAVA_ERROR_LENGTH = 240
INGEST_JOBS_LIMIT = 10
STRAVA_ACTIVITIES_LIMIT = 10
TOKEN_EXPIRES_SOON_WINDOW = timedelta(hours=24)


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


@dataclass(frozen=True)
class DashboardConnectionStatus:
    status: str
    error: str | None
    athlete_id: int | None
    scope: str | None
    token_expires_at_moscow: str
    token_state: str


@dataclass(frozen=True)
class DashboardStravaActivityRow:
    strava_activity_id: int | None
    name: str
    sport_type: str
    start_date_moscow: str
    distance_km: str
    moving_time: str
    elapsed_time: str
    received_at_moscow: str


@dataclass(frozen=True)
class DashboardStravaActivitiesStatus:
    status: str
    error: str | None
    activities: list[DashboardStravaActivityRow]
    total_count: int | None


@dataclass(frozen=True)
class DashboardData:
    system: DashboardSystemStatus
    ingest_jobs: DashboardIngestJobsStatus
    connection: DashboardConnectionStatus
    strava_activities: DashboardStravaActivitiesStatus


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


def _format_duration_seconds(value: int | None) -> str:
    if value is None or value < 0:
        return "—"
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    if minutes > 0:
        return f"{minutes}m"
    return f"{seconds}s"


def _format_distance_km(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1000:.1f}"


def _get_database_status() -> tuple[str, str | None]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return "ok", None
    except Exception as exc:
        return "error", _sanitize_database_error(exc)


def _resolve_token_state(expires_at: datetime | None, *, now: datetime) -> str:
    if expires_at is None:
        return "unknown"
    if expires_at < now:
        return "expired"
    if expires_at <= now + TOKEN_EXPIRES_SOON_WINDOW:
        return "expires_soon"
    return "valid"


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


def get_dashboard_connection_status() -> DashboardConnectionStatus:
    now = datetime.now(MOSCOW_TZ)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        strava_athlete_id,
                        scope,
                        expires_at
                    from user_strava_connection
                    order by updated_at desc, id desc
                    limit 1;
                    """
                )
                row = cur.fetchone()

        if not row:
            return DashboardConnectionStatus(
                status="not_connected",
                error=None,
                athlete_id=None,
                scope=None,
                token_expires_at_moscow="—",
                token_state="unknown",
            )

        expires_at = row[2]
        return DashboardConnectionStatus(
            status="connected",
            error=None,
            athlete_id=row[0],
            scope=row[1],
            token_expires_at_moscow=_format_moscow_timestamp(expires_at),
            token_state=_resolve_token_state(expires_at, now=now),
        )
    except Exception as exc:
        return DashboardConnectionStatus(
            status="error",
            error=_sanitize_database_error(exc),
            athlete_id=None,
            scope=None,
            token_expires_at_moscow="—",
            token_state="unknown",
        )


def get_dashboard_strava_activities_status() -> DashboardStravaActivitiesStatus:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from strava_activity_raw;")
                count_row = cur.fetchone() or (0,)

                cur.execute(
                    """
                    select
                        strava_activity_id,
                        coalesce(nullif(trim(name), ''), nullif(trim(raw_json ->> 'name'), '')) as activity_name,
                        coalesce(
                            nullif(trim(activity_type), ''),
                            nullif(trim(raw_json ->> 'sport_type'), ''),
                            nullif(trim(raw_json ->> 'type'), '')
                        ) as activity_type_label,
                        coalesce(
                            start_date,
                            nullif(raw_json ->> 'start_date', '')::timestamptz,
                            nullif(raw_json ->> 'start_date_local', '')::timestamptz
                        ) as activity_start_date,
                        coalesce(
                            distance_m,
                            nullif(raw_json ->> 'distance', '')::double precision
                        ) as activity_distance_m,
                        coalesce(
                            moving_time_s,
                            nullif(raw_json ->> 'moving_time', '')::integer
                        ) as activity_moving_time_s,
                        coalesce(
                            elapsed_time_s,
                            nullif(raw_json ->> 'elapsed_time', '')::integer
                        ) as activity_elapsed_time_s,
                        coalesce(updated_at, fetched_at) as activity_received_at
                    from strava_activity_raw
                    order by start_date desc nulls last, updated_at desc, id desc
                    limit %s;
                    """,
                    (STRAVA_ACTIVITIES_LIMIT,),
                )
                rows = cur.fetchall()

        activities = [
            DashboardStravaActivityRow(
                strava_activity_id=row[0],
                name=_truncate_text(row[1], limit=80),
                sport_type=_truncate_text(row[2], limit=40),
                start_date_moscow=_format_moscow_timestamp(row[3]),
                distance_km=_format_distance_km(row[4]),
                moving_time=_format_duration_seconds(row[5]),
                elapsed_time=_format_duration_seconds(row[6]),
                received_at_moscow=_format_moscow_timestamp(row[7]),
            )
            for row in rows
        ]

        return DashboardStravaActivitiesStatus(
            status="ok",
            error=None,
            activities=activities,
            total_count=count_row[0],
        )
    except Exception as exc:
        return DashboardStravaActivitiesStatus(
            status="error",
            error=_truncate_text(_sanitize_database_error(exc), limit=MAX_STRAVA_ERROR_LENGTH),
            activities=[],
            total_count=None,
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


def get_dashboard_data() -> DashboardData:
    return DashboardData(
        system=get_dashboard_system_status(),
        ingest_jobs=get_dashboard_ingest_jobs_status(),
        connection=get_dashboard_connection_status(),
        strava_activities=get_dashboard_strava_activities_status(),
    )
