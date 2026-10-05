import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.background import BackgroundScheduler

from conductor.application.heartbeat import HeartbeatDecision, HeartbeatLog, send_heartbeat
from conductor.application.ports import Heartbeat

log = structlog.get_logger()
HEARTBEAT_JOB_ID = "heartbeat"
INGEST_JOB_ID = "ledger_ingest"
FENCE_JOB_ID = "daily_fence"
FENCE_STARTUP_JOB_ID = "daily_fence_startup"
VALUATION_JOB_ID = "cad_valuation"
RISK_JOB_ID = "risk_cycle"
RISK_STARTUP_JOB_ID = "risk_cycle_startup"
BACKUP_JOB_ID = "nightly_backup"
BACKUP_HOUR_UTC, BACKUP_MINUTE_UTC = 3, 15

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
    # 3A-5. None = backups not configured (no job is scheduled).
    backup: Callable[[], object] | None = None


def build_scheduler(
    heartbeat: Heartbeat,
    *,
    heartbeat_interval_seconds: int,
    ledger_jobs: LedgerJobs | None = None,
    heartbeat_decision: Callable[[], HeartbeatDecision] = lambda: HeartbeatDecision(True),
    heartbeat_history: HeartbeatLog | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BackgroundScheduler:
    """UTC scheduler. Job failures are logged, never propagated. Ledger jobs share
    one lock so Conductor's own writes never overlap (SQLite, single writer). The backup
    job deliberately does NOT take that lock: an upload must never delay a risk cycle."""
    scheduler = BackgroundScheduler(timezone="UTC")
    ledger_lock = threading.Lock()

    def heartbeat_job() -> None:
        try:
            send_heartbeat(heartbeat, heartbeat_decision, now=clock, history=heartbeat_history)
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
        if ledger_jobs.backup is not None:
            backup = ledger_jobs.backup

            def backup_job() -> None:
                try:
                    backup()
                except Exception:
                    log.exception("job_failed", job=BACKUP_JOB_ID)

            # Nightly, outside the ledger lock. misfire grace lets a late start still run it.
            scheduler.add_job(
                backup_job,
                "cron",
                hour=BACKUP_HOUR_UTC,
                minute=BACKUP_MINUTE_UTC,
                id=BACKUP_JOB_ID,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
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
