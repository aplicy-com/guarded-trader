"""Halt use cases: engage, enforce, clear, kill switch, nuclear.

The ledger is the source of truth. Every action records the halt FIRST, then
touches Freqtrade, so a failed call can never leave Freqtrade trading under a
halt the ledger does not know about; `enforce_halts` retries whatever failed.
Nothing here clears a halt except `clear_halt`, which needs an operator name.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import structlog

from conductor.application.ingest import FreqtradeInstance
from conductor.application.ledger_ports import Ledger
from conductor.application.notify import safe_send
from conductor.application.ports import Notifier
from conductor.domain.halt import Halt, HaltType, entries_blocked

log = structlog.get_logger()
Clock = Callable[[], datetime]

FLATTEN_WAIT_SECONDS = 30.0
FLATTEN_POLL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class StepResult:
    instance: str
    step: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class HaltReport:
    halt_id: int
    created: bool  # False: an identical halt was already active
    steps: tuple[StepResult, ...]

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)


def engage_halt(
    ledger: Ledger,
    *,
    halt_type: HaltType,
    reason: str,
    actor: str,
    now: Clock,
    notifier: Notifier,
    instance: str | None = None,
) -> tuple[int, bool]:
    """Record a halt (idempotent per type+instance while active) and alert."""
    at = now()
    with ledger.transaction() as repo:
        for h in repo.active_halts():
            if h.halt_type is halt_type and h.instance == instance:
                return h.id, False
        halt_id = repo.add_halt(halt_type, instance, reason, at, actor)
        repo.add_audit(
            at,
            actor,
            "halt_engaged",
            {"halt_id": halt_id, "type": halt_type.value, "instance": instance, "reason": reason},
        )
    log.error(
        "halt_engaged", halt_id=halt_id, type=halt_type.value, instance=instance, reason=reason
    )
    safe_send(notifier, f"HALT #{halt_id} [{halt_type.value}] {reason}")
    return halt_id, True


def _pause(inst: FreqtradeInstance) -> StepResult:
    if inst.controller is None:
        return StepResult(inst.name, "pause_entries", False, "no write access configured")
    try:
        inst.controller.pause_entries()
    except Exception as exc:
        log.error("halt_pause_failed", instance=inst.name, error=type(exc).__name__)
        return StepResult(inst.name, "pause_entries", False, type(exc).__name__)
    return StepResult(inst.name, "pause_entries", True)


def enforce_halts(ledger: Ledger, instances: list[FreqtradeInstance]) -> tuple[StepResult, ...]:
    """Make every halted instance's Freqtrade actually refuse entries.

    Re-applies after a Freqtrade restart (it comes back "running"). Unknown or
    unreadable state is treated as running: we pause rather than assume. If
    Freqtrade is unreachable the failure is logged and retried next cycle; the
    halt stays active in the ledger regardless. Never resumes anything (starting a freshly
    booted bot is `boot.start_if_clear`'s job).
    """
    with ledger.transaction(write=False) as repo:
        active = repo.active_halts()
    if not active:
        return ()
    results: list[StepResult] = []
    for inst in instances:
        if not entries_blocked(active, inst.name):
            continue
        try:
            state = inst.reader.show_config().state
        except Exception as exc:
            log.error("halt_enforce_unreachable", instance=inst.name, error=type(exc).__name__)
            results.append(StepResult(inst.name, "check_state", False, type(exc).__name__))
            continue
        if state in ("paused", "stopped"):
            continue
        log.error("halt_reapplied", instance=inst.name, observed_state=state or "unknown")
        results.append(_pause(inst))
    return tuple(results)


def kill_switch(
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    *,
    operator: str,
    now: Clock,
    notifier: Notifier,
) -> HaltReport:
    """Block new entries on every instance. Open positions keep being managed."""
    operator = _operator(operator)
    halt_id, created = engage_halt(
        ledger,
        halt_type=HaltType.KILL_SWITCH,
        reason=f"kill switch engaged by {operator}",
        actor=operator,
        now=now,
        notifier=notifier,
    )
    steps = [_pause(inst) for inst in instances]
    _audit_steps(ledger, now, operator, "kill_switch_applied", halt_id, steps)
    report = HaltReport(halt_id, created, tuple(steps))
    if not report.ok:  # success is already announced by the halt alert itself
        safe_send(notifier, _result_text("KILL SWITCH", report))
    return report


def nuclear(
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    *,
    operator: str,
    now: Clock,
    notifier: Notifier,
    sleep: Callable[[float], None] = time.sleep,
    flatten_wait_seconds: float = FLATTEN_WAIT_SECONDS,
) -> HaltReport:
    """Pause entries, cancel open orders, market-exit everything, then stop.

    Order matters: orders are cancelled and positions exited while the bot is
    still running (Freqtrade refuses both once stopped), and `stop` is only sent
    after the account is confirmed flat. If it is not flat in time, the bot is
    left PAUSED (still managing its exits) and the step is reported as failed.
    Each instance is independent; each step's outcome is audited.
    """
    operator = _operator(operator)
    halt_id, created = engage_halt(
        ledger,
        halt_type=HaltType.NUCLEAR,
        reason=f"nuclear protocol engaged by {operator}",
        actor=operator,
        now=now,
        notifier=notifier,
    )
    steps: list[StepResult] = []
    for inst in instances:
        steps.extend(_nuclear_one(inst, sleep, flatten_wait_seconds))
    _audit_steps(ledger, now, operator, "nuclear_applied", halt_id, steps)
    report = HaltReport(halt_id, created, tuple(steps))
    safe_send(notifier, _result_text("NUCLEAR", report))
    return report


def _nuclear_one(
    inst: FreqtradeInstance, sleep: Callable[[float], None], wait_seconds: float
) -> list[StepResult]:
    steps = [_pause(inst)]
    ctl = inst.controller
    if ctl is None:
        return steps
    try:
        open_trades = inst.reader.status()
        for t in open_trades:
            if t.has_open_orders:
                try:
                    ctl.cancel_open_order(t.trade_id)
                    steps.append(StepResult(inst.name, f"cancel_order:{t.trade_id}", True))
                except Exception as exc:
                    steps.append(
                        StepResult(
                            inst.name, f"cancel_order:{t.trade_id}", False, type(exc).__name__
                        )
                    )
        if open_trades:
            ctl.force_exit_all()
            steps.append(StepResult(inst.name, "force_exit_all", True))
        waited = 0.0
        flat = not open_trades
        while not flat and waited < wait_seconds:
            sleep(FLATTEN_POLL_SECONDS)
            waited += FLATTEN_POLL_SECONDS
            flat = not inst.reader.status()
        if not flat:
            steps.append(
                StepResult(
                    inst.name, "confirm_flat", False, "not flat in time; left PAUSED, not stopped"
                )
            )
            return steps
        steps.append(StepResult(inst.name, "confirm_flat", True))
        ctl.stop()
        steps.append(StepResult(inst.name, "stop", True))
    except Exception as exc:
        log.error("nuclear_step_failed", instance=inst.name, error=type(exc).__name__)
        steps.append(StepResult(inst.name, "nuclear", False, type(exc).__name__))
    return steps


def _result_text(name: str, report: HaltReport) -> str:
    head = f"{name} #{report.halt_id}: " + (
        "all steps ok" if report.ok else "NOT every step succeeded"
    )
    lines = [head]
    lines += [
        f"  {s.instance}: {s.step}: {'ok' if s.ok else 'FAILED ' + s.detail}" for s in report.steps
    ]
    if not report.ok:
        lines.append("The halt is recorded and will be re-applied automatically.")
    return "\n".join(lines)


def _operator(operator: str) -> str:
    if not operator.strip():
        raise ValueError("operator must not be empty")
    return operator.strip()


def _audit_steps(
    ledger: Ledger,
    now: Clock,
    actor: str,
    action: str,
    halt_id: int,
    steps: list[StepResult],
) -> None:
    with ledger.transaction() as repo:
        repo.add_audit(
            now(),
            actor,
            action,
            {
                "halt_id": halt_id,
                "steps": [
                    f"{s.instance}:{s.step}:{'ok' if s.ok else 'FAILED ' + s.detail}" for s in steps
                ],
            },
        )


@dataclass(frozen=True, slots=True)
class ClearReport:
    halt_id: int
    newly_cleared: bool
    still_active: tuple[Halt, ...]
    resumed: tuple[StepResult, ...]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.resumed)


def clear_halt(
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    *,
    halt_id: int,
    operator: str,
    note: str | None,
    now: Clock,
    notifier: Notifier | None = None,
) -> ClearReport:
    """The only way out of a halt: a named human. Records the clear, then resumes.

    The clear is committed BEFORE Freqtrade is told to resume, so a failed resume
    leaves Freqtrade paused (safe). Re-running for an already-cleared halt retries
    the resume. An instance is resumed only if no other active halt covers it; a
    breach that is still true simply re-halts on the next risk cycle.
    """
    operator = _operator(operator)
    at = now()
    with ledger.transaction() as repo:
        halt = repo.get_halt(halt_id)
        if halt is None:
            raise ValueError(f"no halt with id {halt_id}")
        newly = repo.is_halt_active(halt_id)
        if newly:
            repo.clear_halt(halt_id, at, operator, note)
            repo.add_audit(
                at,
                operator,
                "halt_cleared",
                {"halt_id": halt_id, "type": halt.halt_type.value, "note": note},
            )
        active = repo.active_halts()
    if newly:
        log.warning("halt_cleared", halt_id=halt_id, operator=operator)
        safe_send(notifier, f"HALT #{halt_id} [{halt.halt_type.value}] cleared by {operator}")
    results: list[StepResult] = []
    for inst in instances:
        if entries_blocked(active, inst.name):
            continue
        if inst.controller is None:
            results.append(StepResult(inst.name, "resume", False, "no write access configured"))
            continue
        try:
            inst.controller.resume()
            results.append(StepResult(inst.name, "resume", True))
        except Exception as exc:
            log.error("halt_resume_failed", instance=inst.name, error=type(exc).__name__)
            results.append(StepResult(inst.name, "resume", False, type(exc).__name__))
    return ClearReport(halt_id, newly, tuple(active), tuple(results))
