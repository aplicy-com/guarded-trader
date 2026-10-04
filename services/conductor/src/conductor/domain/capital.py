"""R1/R2: principal check and the capital formula. Pure; no I/O.

Terminology (single source of truth for this module):

- ``realized_profit``  cumulative realized P&L of closed trades (fees included,
  may be negative). Gross of fencing.
- ``fenced_total``     cumulative profit fenced by R3 (ledger-only).
- ``working_profit``   ``realized_profit - fenced_total``: profit not yet fenced.
- ``max_deployed_capital`` ``principal + working_profit``, floored at zero.
  Equivalently ``principal + realized_profit - fenced_total``; fenced profit is
  subtracted exactly once.
"""

from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)


class PrincipalMismatchError(RuntimeError):
    """The configured principal differs from the one recorded in the ledger (R1)."""


@dataclass(frozen=True, slots=True)
class CapitalSnapshot:
    principal: Decimal
    realized_profit: Decimal
    fenced_total: Decimal
    working_profit: Decimal
    max_deployed_capital: Decimal


def compute_capital(
    principal: Decimal, realized_profit: Decimal, fenced_total: Decimal
) -> CapitalSnapshot:
    """R2: ``max_deployed_capital = principal + working_profit`` (floored at 0).

    There is deliberately no other input: no override, no top-up (AC2.3).
    """
    for name, value in (
        ("principal", principal),
        ("realized_profit", realized_profit),
        ("fenced_total", fenced_total),
    ):
        if not value.is_finite():
            raise ValueError(f"{name} must be finite")
    if principal <= ZERO:
        raise ValueError("principal must be > 0")
    if fenced_total < ZERO:
        raise ValueError("fenced_total must be >= 0")
    working_profit = realized_profit - fenced_total
    return CapitalSnapshot(
        principal=principal,
        realized_profit=realized_profit,
        fenced_total=fenced_total,
        working_profit=working_profit,
        max_deployed_capital=max(ZERO, principal + working_profit),
    )


def check_principal(recorded: Decimal | None, configured: Decimal) -> bool:
    """R1: True if the principal must be recorded now (none exists yet).

    False if it exists and equals ``configured``. Raises
    :class:`PrincipalMismatchError` on any difference: the recorded value is
    never overwritten.
    """
    if not configured.is_finite() or configured <= ZERO:
        raise ValueError("configured principal must be a finite value > 0")
    if recorded is None:
        return True
    if recorded != configured:  # Decimal equality is numeric: 100 == 100.00
        raise PrincipalMismatchError(
            f"configured principal {configured} != ledger principal {recorded}"
        )
    return False
