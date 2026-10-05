"""Fail-closed Freqtrade boot (ADR-0018).

Freqtrade boots PAUSED (`initial_state: paused`): it manages exits of open positions but cannot
open a new one. Only Conductor ever sends `start`, and only when no halt covers the instance:

* on its own startup (the first successful observation of each instance), and
* after it detects a Freqtrade restart (Freqtrade's `/health` `bot_startup_ts` changed).

So between a Freqtrade boot and Conductor's decision the bot cannot trade, and a restart while a
halt is active leaves it paused with no window at all. If Conductor is down, Freqtrade stays
paused (no new entries; exits still managed): that is the intended failure direction.

A pending start is retried every cycle until it succeeds, is no longer wanted (a halt appeared,
or the bot is already running or stopped), or the instance is unreachable. A halt that appears
between the decision and the `start` call is caught by re-checking right after it.
"""

import threading
from collections.abc import Callable
from datetime import datetime

import structlog

from conductor.application.halts import StepResult, enforce_halts
from conductor.application.ingest import FreqtradeInstance
from conductor.application.ledger_ports import Ledger
from conductor.application.notify import safe_send
from conductor.application.ports import Notifier
from conductor.domain.halt import entries_blocked

log = structlog.get_logger()
Clock = Callable[[], datetime]


class BootGuard:
    """What Conductor remembers (in memory) about each Freqtrade's last-seen startup marker.

    Forgetting on a Conductor restart is intended: the first observation of every instance is
    treated as a boot to decide on."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, int | None] = {}
        self._pending: set[str] = set()

    def observe(self, instance: str, marker: int | None) -> bool:
        """Record the marker; True if this is a first sight or the marker changed (a boot)."""
        with self._lock:
            boot = instance not in self._seen or self._seen[instance] != marker
            self._seen[instance] = marker
            if boot:
                self._pending.add(instance)
            return boot

    def is_pending(self, instance: str) -> bool:
        with self._lock:
            return instance in self._pending

    def settle(self, instance: str) -> None:
        with self._lock:
            self._pending.discard(instance)


def start_if_clear(
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    guard: BootGuard,
    *,
    equity_known: bool,
    notifier: Notifier | None = None,
) -> tuple[StepResult, ...]:
    """Start every freshly booted, paused Freqtrade that no active halt covers.

    Call it AFTER this cycle's ingest, risk evaluation and `enforce_halts`, so a breach found in
    the same cycle has already become a halt. ``equity_known=False`` (an ingest failed, so R4
    could not be evaluated) defers every start.
    """
    results: list[StepResult] = []
    for inst in instances:
        if inst.controller is None:
            continue
        try:
            state = inst.reader.show_config().state
            marker = inst.reader.health().startup_ts
        except Exception as exc:
            log.warning("boot_check_unreachable", instance=inst.name, error=type(exc).__name__)
            continue  # nothing recorded: the next cycle is a first sight again
        if guard.observe(inst.name, marker):
            log.warning("freqtrade_boot_detected", instance=inst.name, state=state or "unknown")
        if not guard.is_pending(inst.name):
            continue
        if state == "running":
            guard.settle(inst.name)  # already trading (an operator started it, or an old config)
            continue
        if state != "paused":  # "stopped" is deliberate (nuclear); "" is unknown: never guess
            if state == "stopped":
                guard.settle(inst.name)
            continue
        if not equity_known:
            log.warning("boot_start_deferred", instance=inst.name, reason="equity unknown")
            continue
        with ledger.transaction(write=False) as repo:
            blocked = entries_blocked(repo.active_halts(), inst.name)
        if blocked:
            guard.settle(inst.name)  # stays paused; `clear-halt` resumes it when a human clears
            log.warning("boot_start_withheld", instance=inst.name, reason="halt active")
            continue
        try:
            inst.controller.resume()
        except Exception as exc:
            log.error("boot_start_failed", instance=inst.name, error=type(exc).__name__)
            results.append(StepResult(inst.name, "boot_start", False, type(exc).__name__))
            continue  # still pending: retried next cycle
        guard.settle(inst.name)
        results.append(StepResult(inst.name, "boot_start", True))
        safe_send(
            notifier, f"BOOT {inst.name}: Freqtrade restarted paused; no halt active, started"
        )
        # A halt raised in the instant between the check and `start` (say a /kill) must win.
        results.extend(enforce_halts(ledger, [inst]))
    return tuple(results)
