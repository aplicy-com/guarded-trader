from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthReport:
    ok: bool
    db_ok: bool
    db_journal_mode: str
    scheduler_running: bool


def check_health(
    probe_db: Callable[[], str],
    scheduler_running: Callable[[], bool],
    *,
    scheduler_required: bool,
) -> HealthReport:
    """Use case: is Conductor itself healthy? Self-contained: never calls Freqtrade.

    `probe_db` returns the SQLite journal mode (raises if the DB is unusable);
    ADR-0009 requires "wal".
    """
    try:
        mode = probe_db().lower()
        db_ok = mode == "wal"
    except Exception:
        mode, db_ok = "error", False
    running = scheduler_running()
    ok = db_ok and (running or not scheduler_required)
    return HealthReport(ok=ok, db_ok=db_ok, db_journal_mode=mode, scheduler_running=running)
