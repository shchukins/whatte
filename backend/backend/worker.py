import logging
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.core.logging import configure_logging, log_event
from backend.services.ingest_service import process_one_strava_ingest_job
from backend.services.daily_readiness_pipeline import recompute_daily_readiness
from backend.services.notification_service import send_daily_readiness
from backend.services.subjective_feedback_service import schedule_next_day_recovery_prompts
from backend.services.rpe_service import reconcile_recent_strava_rpe


configure_logging()
logger = logging.getLogger(__name__)

DAILY_READINESS_USER_ID = settings.daily_readiness_user_id
DAILY_READINESS_FALLBACK_HOUR_UTC = settings.daily_readiness_fallback_hour_utc
DAILY_READINESS_FALLBACK_MINUTE_UTC = settings.daily_readiness_fallback_minute_utc
NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC = settings.next_day_recovery_prompt_hour_utc
WHATTE_TIMEZONE = settings.whatte_timezone

_last_daily_readiness_date: date | None = None
_last_rpe_reconciliation_date: date | None = None


def _local_date(now: datetime) -> date:
    return now.astimezone(ZoneInfo(WHATTE_TIMEZONE)).date()


def maybe_send_daily_readiness() -> None:
    global _last_daily_readiness_date
    now = datetime.now(timezone.utc)

    if (
        now.hour != DAILY_READINESS_FALLBACK_HOUR_UTC
        or now.minute < DAILY_READINESS_FALLBACK_MINUTE_UTC
    ):
        return

    notification_date = _local_date(now)
    if _last_daily_readiness_date == notification_date:
        return

    recompute_daily_readiness(
        user_id=DAILY_READINESS_USER_ID,
        target_date=notification_date.isoformat(),
    )
    sent = send_daily_readiness(
        DAILY_READINESS_USER_ID,
        notification_date=notification_date,
    )
    _last_daily_readiness_date = notification_date

    if sent:
        log_event(
            logger,
            "daily_readiness_fallback_sent",
            user_id=DAILY_READINESS_USER_ID,
        )


def maybe_schedule_next_day_recovery_prompts() -> None:
    now = datetime.now(timezone.utc)

    if now.hour != NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC:
        return

    result = schedule_next_day_recovery_prompts(target_date=_local_date(now))
    log_event(
        logger,
        "next_day_recovery_prompt_scheduler_ran",
        target_date=result["target_date"],
        processed_users=result["processed_users"],
        sent_count=result["sent_count"],
        skipped_count=result["skipped_count"],
        failed_count=result["failed_count"],
    )


def maybe_reconcile_recent_rpe() -> None:
    global _last_rpe_reconciliation_date
    now = datetime.now(timezone.utc)
    today = _local_date(now)
    if now.hour != DAILY_READINESS_FALLBACK_HOUR_UTC:
        return
    if _last_rpe_reconciliation_date == today:
        return
    _last_rpe_reconciliation_date = today
    result = reconcile_recent_strava_rpe(DAILY_READINESS_USER_ID)
    log_event(logger, "strava_rpe_reconciled", user_id=DAILY_READINESS_USER_ID, **result)


def main() -> None:
    log_event(logger, "worker_started")

    while True:
        try:
            maybe_send_daily_readiness()
            maybe_schedule_next_day_recovery_prompts()
            try:
                maybe_reconcile_recent_rpe()
            except Exception as error:
                log_event(
                    logger,
                    "strava_rpe_reconciliation_failed",
                    level=logging.ERROR,
                    error_type=type(error).__name__,
                    error=str(error),
                )
            result = process_one_strava_ingest_job()

            if result.get("message") == "no pending jobs":
                log_event(logger, "worker_idle", sleep_seconds=10)
                time.sleep(10)
            else:
                log_event(
                    logger,
                    "strava_ingest_job_processed",
                    job_id=result.get("job_id"),
                    user_id=result.get("user_id"),
                    activity_id=result.get("activity_id"),
                    result=result,
                )
                time.sleep(1)

        except Exception as e:
            log_event(
                logger,
                "error",
                level=logging.ERROR,
                error_type=type(e).__name__,
                error=str(e),
                context="worker_loop",
            )
            time.sleep(5)


if __name__ == "__main__":
    main()
