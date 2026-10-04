"""R3: profit fence planning and manual-move due checks. Pure; no I/O."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

ZERO = Decimal(0)
MANUAL_MOVE_MAX_AGE_DAYS = 30  # R3: "one calendar month" since the last transfer (draft)


def plan_fence(working_profit: Decimal, daily_profit_cap: Decimal) -> Decimal:
    """Amount to fence: the part of working profit above the cap (never negative)."""
    if daily_profit_cap < ZERO:
        raise ValueError("daily_profit_cap must be >= 0")
    return max(ZERO, working_profit - daily_profit_cap)


def missed_fence_days(last_fence_date: date | None, today: date) -> tuple[date, ...]:
    """UTC days strictly between the last recorded fence run and ``today`` (AC3.6).

    Empty on first ever run, or when the last run was yesterday/today.
    """
    if last_fence_date is None or last_fence_date >= today:
        return ()
    gap = (today - last_fence_date).days - 1
    return tuple(last_fence_date + timedelta(days=i) for i in range(1, gap + 1))


@dataclass(frozen=True, slots=True)
class MoveDue:
    unmoved: Decimal
    over_threshold: bool
    month_elapsed: bool

    @property
    def due(self) -> bool:
        return self.over_threshold or self.month_elapsed


def manual_move_due(
    *,
    fenced_total: Decimal,
    moved_total: Decimal,
    threshold: Decimal,
    now: datetime,
    since: datetime | None,
) -> MoveDue:
    """AC3.4: due when fenced-but-unmoved >= threshold, or >= 30 days since ``since``.

    ``since`` is the last manual transfer, or, if none yet, the first positive
    fence. Nothing is due while nothing is unmoved. This only reports; it never
    acts (the move is always manual).
    """
    unmoved = fenced_total - moved_total
    if unmoved < ZERO:
        raise ValueError("moved_total exceeds fenced_total")
    if unmoved == ZERO:
        return MoveDue(unmoved, False, False)
    elapsed = since is not None and now - since >= timedelta(days=MANUAL_MOVE_MAX_AGE_DAYS)
    return MoveDue(unmoved, unmoved >= threshold, elapsed)


def validate_transfer(amount: Decimal, fenced_total: Decimal, moved_total: Decimal) -> None:
    """A manual transfer must be positive and cannot exceed fenced-but-unmoved profit."""
    if not amount.is_finite() or amount <= ZERO:
        raise ValueError("transfer amount must be a finite value > 0")
    if amount > fenced_total - moved_total:
        raise ValueError(
            f"transfer {amount} exceeds fenced-but-unmoved {fenced_total - moved_total}"
        )
