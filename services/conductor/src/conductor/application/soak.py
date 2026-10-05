"""Live-pilot soak gate (ADR-0019): the dry-run system must have run clean for 72 hours.

Evaluated against the DRY-RUN ledger, before the switch to live. "Clean" is deliberately narrow
and checkable from that ledger alone:

* the soak window (since the recorded start, 2026-10-05 rebuild) is at least ``required``;
* no halt was raised by the system itself (a risk breach: daily loss, drawdown, loss streak,
  capital or position cap) since the start. Halts a human engaged (kill switch, nuclear, drills)
  do not count against it: they are the controls working;
* no halt is active right now (a live start with an active halt would never trade anyway, and
  an unresolved halt means the soak is not finished).

Conductor downtime is NOT visible from the ledger; healthchecks.io's log is the record of that,
and the go-live runbook has the operator check it. This gate cannot prove it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from conductor.application.ledger_ports import Ledger
from conductor.domain.halt import Halt

DEFAULT_REQUIRED = timedelta(hours=72)
SYSTEM_ACTOR = "system"


@dataclass(frozen=True, slots=True)
class SoakStatus:
    started_at: datetime
    now: datetime
    required: timedelta
    system_halts: tuple[Halt, ...]
    active_halts: tuple[Halt, ...]

    @property
    def elapsed(self) -> timedelta:
        return self.now - self.started_at

    @property
    def time_met(self) -> bool:
        return self.elapsed >= self.required

    @property
    def clean(self) -> bool:
        return not self.system_halts and not self.active_halts

    @property
    def ok(self) -> bool:
        return self.time_met and self.clean


def check_soak(
    ledger: Ledger,
    *,
    started_at: datetime,
    now: datetime,
    required: timedelta = DEFAULT_REQUIRED,
) -> SoakStatus:
    if started_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    if required <= timedelta(0):
        raise ValueError("required must be positive")
    with ledger.transaction(write=False) as repo:
        every = repo.list_halts(10_000)
        active = tuple(repo.active_halts())
    system = tuple(
        halt
        for halt, _, _ in every
        if halt.created_by == SYSTEM_ACTOR and halt.created_at >= started_at
    )
    return SoakStatus(started_at, now, required, system, active)
