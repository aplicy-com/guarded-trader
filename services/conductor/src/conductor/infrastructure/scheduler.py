import threading
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from apscheduler.schedulers.background import BackgroundScheduler

from conductor.application.heartbeat import send_heartbeat
from conductor.application.ports import Heartbeat

log = structlog.get_logger()
HEARTBEAT_JOB_ID = "heartbeat"
INGEST_JOB_ID = "ledger_ingest"
FENCE_JOB_ID = "daily_fence"
FENCE_STARTUP_JOB_ID = "daily_fence_startup"
VALUATION_JOB_ID = "cad_valuation"
RISK_JOB_ID = "risk_cycle"
RISK_STARTUP_JOB_ID = "risk_cycle_startup"

VALUATION_INTERVAL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class LedgerJobs:
    """Callables for the ledger jobs; each is wrapped so a failure is logged, never raised."""

    ingest: Callable[[], object]
    fence: Callable[[], object]
    valuation: Callable[[], object]
    ingest_interval_seconds: int
    risk: Callable[[], object] | None = None
    risk_interval_seconds: int = 60


def build_scheduler(
    heartbeat: Heartbeat,
    *,
    heartbeat_interval_seconds: int,
    ledger_jobs: LedgerJobs | None = None,
) -> BackgroundScheduler:
    """UTC scheduler. Job failures are logged, never propagated. Ledger jobs share
    one lock so Conductor's own writes never overlap (SQLite, single writer)."""
    scheduler = BackgroundScheduler(timezone="UTC")
    ledger_lock = threading.Lock()

    def heartbeat_job() -> None:
        try:
            send_heartbeat(heartbeat)
        except Exception:
            log.exception("heartbeat_failed")

    def guarded(name: str, fn: Callable[[], object]) -> Callable[[], None]:
        def run() -> None:
            with ledger_lock:
                try:
                    fn()
                except Exception:
                    log.exception("job_failed", job=name)

        return run

    scheduler.add_job(
        heartbeat_job,
        "interval",
        seconds=heartbeat_interval_seconds,
        id=HEARTBEAT_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    if ledger_jobs is not None:
        scheduler.add_job(
            guarded(INGEST_JOB_ID, ledger_jobs.ingest),
            "interval",
            seconds=ledger_jobs.ingest_interval_seconds,
            id=INGEST_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        # R3: once per UTC day. misfire grace lets a late start still run it.
        scheduler.add_job(
            guarded(FENCE_JOB_ID, ledger_jobs.fence),
            "cron",
            hour=0,
            minute=5,
            id=FENCE_JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        # Catch-up on every start: a missed UTC day is fenced now, not tomorrow (AC3.6).
        scheduler.add_job(
            guarded(FENCE_STARTUP_JOB_ID, ledger_jobs.fence),
            "date",
            id=FENCE_STARTUP_JOB_ID,
        )
        scheduler.add_job(
            guarded(VALUATION_JOB_ID, ledger_jobs.valuation),
            "interval",
            seconds=VALUATION_INTERVAL_SECONDS,
            id=VALUATION_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        if ledger_jobs.risk is not None:
            # R4/R2/R7 + halt enforcement. Runs once on start, then on a short interval.
            scheduler.add_job(
                guarded(RISK_JOB_ID, ledger_jobs.risk),
                "interval",
                seconds=ledger_jobs.risk_interval_seconds,
                id=RISK_JOB_ID,
                max_instances=1,
                coalesce=True,
            )
            scheduler.add_job(
                guarded(RISK_STARTUP_JOB_ID, ledger_jobs.risk), "date", id=RISK_STARTUP_JOB_ID
            )
    return scheduler
