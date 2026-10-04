import structlog
from apscheduler.schedulers.background import BackgroundScheduler

from conductor.application.heartbeat import send_heartbeat
from conductor.application.ports import Heartbeat

log = structlog.get_logger()
HEARTBEAT_JOB_ID = "heartbeat"


def build_scheduler(
    heartbeat: Heartbeat, *, heartbeat_interval_seconds: int
) -> BackgroundScheduler:
    """UTC scheduler. Job failures are logged, never propagated. Later jobs
    (ingest, fence, risk checks) are registered here in 3A-2/3A-3."""
    scheduler = BackgroundScheduler(timezone="UTC")

    def heartbeat_job() -> None:
        try:
            send_heartbeat(heartbeat)
        except Exception:
            log.exception("heartbeat_failed")

    scheduler.add_job(
        heartbeat_job,
        "interval",
        seconds=heartbeat_interval_seconds,
        id=HEARTBEAT_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
