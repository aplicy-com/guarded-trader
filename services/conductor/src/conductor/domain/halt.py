"""Halt model (R4/R2/R7, kill switch, nuclear). Pure; no I/O.

A halt is an immutable fact ("entries are blocked, and why"). It stays active
until a human clears it; clearing is a separate fact. Nothing here ever expires
or clears a halt by itself.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class HaltType(StrEnum):
    DAILY_LOSS = "daily_loss"  # R4 AC4.1
    MAX_DRAWDOWN = "max_drawdown"  # R4 AC4.2
    CONSECUTIVE_LOSSES = "consecutive_losses"  # R4 AC4.3
    CAPITAL_EXCEEDED = "capital_exceeded"  # R2: exposure above max_deployed_capital
    MAX_POSITIONS = "max_positions"  # R7: correlation guard
    KILL_SWITCH = "kill_switch"  # manual: block new entries
    NUCLEAR = "nuclear"  # manual: cancel orders, flatten, stop


@dataclass(frozen=True, slots=True)
class Halt:
    id: int
    halt_type: HaltType
    instance: str | None  # None = every instance
    reason: str
    created_at: datetime
    created_by: str  # "system" or an operator identity


@dataclass(frozen=True, slots=True)
class HaltClear:
    halt_id: int
    cleared_at: datetime
    operator: str
    note: str | None


def applies_to(halt: Halt, instance: str) -> bool:
    return halt.instance is None or halt.instance == instance


def entries_blocked(active_halts: Iterable[Halt], instance: str) -> bool:
    """True if any active halt covers ``instance``. The only way back is a human clear."""
    return any(applies_to(h, instance) for h in active_halts)
