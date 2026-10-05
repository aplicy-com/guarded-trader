"""Heartbeat (3A-5): decide whether Conductor is healthy, then push one outbound ping.

Push, never pull: the monitoring service (healthchecks.io) owns noticing silence. A ping
means "alive and healthy"; an unhealthy Conductor pings the check's /fail endpoint with a
short reason; a dead Conductor or VPS pings nothing, and the service alerts on its own.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from conductor.application.health import HealthReport
from conductor.application.ports import Heartbeat

log = structlog.get_logger()

# The risk cycle runs every RISK_CHECK_INTERVAL_SECONDS (default 60 s, min 15 s); 3 minutes
# tolerates two missed cycles before the heartbeat goes red.
RISK_CYCLE_MAX_AGE = timedelta(minutes=3)
MAX_REASON_CHARS = 200


@dataclass(frozen=True, slots=True)
class HeartbeatDecision:
    healthy: bool
    reason: str = ""


class RiskCycleMonitor:
    """Remembers when the last risk cycle *completed without raising*. In memory only: a
    restart forgets it, and the heartbeat is then red until the first cycle finishes (the
    startup risk job runs within seconds, well before the first 5-minute heartbeat)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_success: datetime | None = None

    def record_success(self, at: datetime) -> None:
        with self._lock:
            self._last_success = at

    @property
    def last_success(self) -> datetime | None:
        with self._lock:
            return self._last_success


def decide_heartbeat(
    report: HealthReport,
    last_risk_success: datetime | None,
    now: datetime,
    *,
    risk_cycle_required: bool,
    max_risk_age: timedelta = RISK_CYCLE_MAX_AGE,
) -> HeartbeatDecision:
    """Healthy only if the DB is ok, the scheduler is running and the last risk cycle
    succeeded within ``max_risk_age``. Every failing condition is listed in the reason."""
    problems: list[str] = []
    if not report.db_ok:
        problems.append(f"database unhealthy (journal_mode={report.db_journal_mode})")
    if risk_cycle_required:
        if not report.scheduler_running:
            problems.append("scheduler not running")
        if last_risk_success is None:
            problems.append("no successful risk cycle yet")
        else:
            age = now - last_risk_success
            if age > max_risk_age:
                problems.append(
                    f"last successful risk cycle {int(age.total_seconds())}s ago "
                    f"(limit {int(max_risk_age.total_seconds())}s)"
                )
    if not problems:
        return HeartbeatDecision(True)
    return HeartbeatDecision(False, "; ".join(problems)[:MAX_REASON_CHARS])


class HeartbeatLog:
    """What the heartbeat last did, for the dashboard. In memory only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_attempt_at: datetime | None = None
        self.last_ok_at: datetime | None = None
        # "ok" | "fail_sent" (we pinged /fail) | "delivery_failed" (the ping did not go out)
        self.last_outcome: str | None = None
        self.last_reason: str = ""

    def record(self, at: datetime, outcome: str, reason: str = "") -> None:
        with self._lock:
            self.last_attempt_at, self.last_outcome, self.last_reason = at, outcome, reason
            if outcome == "ok":
                self.last_ok_at = at

    def snapshot(self) -> tuple[datetime | None, datetime | None, str | None, str]:
        with self._lock:
            return self.last_attempt_at, self.last_ok_at, self.last_outcome, self.last_reason


def send_heartbeat(
    heartbeat: Heartbeat,
    decide: Callable[[], HeartbeatDecision],
    *,
    now: Callable[[], datetime],
    history: HeartbeatLog | None = None,
) -> HeartbeatDecision:
    """Use case: one heartbeat. Pings OK or /fail according to ``decide``. A delivery
    failure is recorded and re-raised for the scheduler to log; it never crashes it."""
    decision = decide()
    try:
        if decision.healthy:
            heartbeat.ok()
        else:
            log.warning("heartbeat_unhealthy", reason=decision.reason)
            heartbeat.fail(decision.reason)
    except Exception:
        if history is not None:
            history.record(now(), "delivery_failed", decision.reason)
        raise
    if history is not None:
        history.record(now(), "ok" if decision.healthy else "fail_sent", decision.reason)
    return decision
