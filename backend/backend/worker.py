import logging
import time
from datetime import datetime, timezone

from backend.config import settings
from backend.core.logging import configure_logging, log_event
from backend.services.ingest_service import process_one_strava_ingest_job
from backend.services.notification_service import send_daily_readiness
from backend.services.subjective_feedback_service import schedule_next_day_recovery_prompts


configure_logging()
logger = logging.getLogger(__name__)

DAILY_READINESS_USER_ID = "sergey"
DAILY_READINESS_HOUR_UTC = 7
NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC = settings.next_day_recovery_prompt_hour_utc


def maybe_send_daily_readiness() -> None:
    now = datetime.now(timezone.utc)

    if now.hour != DAILY_READINESS_HOUR_UTC:
        return

    sent = send_daily_readiness(DAILY_READINESS_USER_ID, for_date=now.date())

    if sent:
        log_event(
            logger,
            "daily_readiness_sent",
            user_id=DAILY_READINESS_USER_ID,
        )


def maybe_schedule_next_day_recovery_prompts() -> None:
    now = datetime.now(timezone.utc)

    if now.hour != NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC:
        return

    result = schedule_next_day_recovery_prompts(target_date=now.date())
    log_event(
        logger,
        "next_day_recovery_prompt_scheduler_ran",
        target_date=result["target_date"],
        processed_users=result["processed_users"],
        sent_count=result["sent_count"],
        skipped_count=result["skipped_count"],
        failed_count=result["failed_count"],
    )


def main() -> None:
    log_event(logger, "worker_started")

    while True:
        try:
            maybe_send_daily_readiness()
            maybe_schedule_next_day_recovery_prompts()

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
