"""R5: account isolation check, per whitelisted base asset. Pure; no I/O.

Only holdings the system itself bought count (AC5.2). The ledger's view of what
the system holds in an asset is the sum of its open long trades' amounts; any
exchange balance beyond that (plus explicitly excluded amounts) is unexplained.
Each asset is judged on its own: a shortfall in one never masks an excess in
another (AC5.5).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class IsolationViolation:
    pair: str
    asset: str
    exchange_balance: Decimal
    ledger_holding: Decimal
    excluded: Decimal
    unexplained: Decimal


def base_asset(pair: str) -> str:
    """'ETH/USD' -> 'ETH'; 'ETH/USD:USD' -> 'ETH'."""
    base, sep, _ = pair.partition("/")
    if not sep or not base:
        raise ValueError(f"not a spot pair: {pair!r}")
    return base


def check_account_isolation(
    whitelist: Iterable[str],
    exchange_balances: Mapping[str, Decimal],
    ledger_holdings: Mapping[str, Decimal],
    excluded: Mapping[str, Decimal] | None = None,
    *,
    tolerance: Decimal = ZERO,
) -> tuple[IsolationViolation, ...]:
    """Return one violation per whitelisted pair whose base balance is unexplained.

    ``exchange_balances`` and ``ledger_holdings`` are keyed by asset code. Only
    an *excess* of exchange balance over (ledger holding + excluded + tolerance)
    is a violation; a shortfall is not (fees/dust are handled elsewhere).
    """
    excluded = excluded or {}
    if tolerance < ZERO:
        raise ValueError("tolerance must be >= 0")
    violations: list[IsolationViolation] = []
    for pair in whitelist:
        asset = base_asset(pair)
        balance = exchange_balances.get(asset, ZERO)
        held = ledger_holdings.get(asset, ZERO)
        excl = excluded.get(asset, ZERO)
        unexplained = balance - held - excl
        if unexplained > tolerance:
            violations.append(IsolationViolation(pair, asset, balance, held, excl, unexplained))
    return tuple(violations)


class _Declaration(Protocol):
    @property
    def asset(self) -> str: ...
    @property
    def amount(self) -> Decimal: ...


def effective_exclusions(history: Iterable[_Declaration]) -> dict[str, Decimal]:
    """Amount in force per asset from an oldest-first declaration history (newest wins).

    Items need ``asset`` and ``amount``. A newest amount of 0 withdraws the exclusion.
    """
    out: dict[str, Decimal] = {}
    for rec in history:
        out[rec.asset] = rec.amount
    return {asset: amount for asset, amount in out.items() if amount > ZERO}


class AccountIsolationError(RuntimeError):
    """Startup must abort: a whitelisted pair holds a balance the system did not buy (R5)."""

    def __init__(self, violations: tuple[IsolationViolation, ...]) -> None:
        self.violations = violations
        detail = "; ".join(f"{v.pair}: unexplained {v.unexplained} {v.asset}" for v in violations)
        super().__init__(
            f"R5 account isolation violated: {detail}. Clear it by hand "
            "(docs/06-runbooks/start-stop.md, 'R5 abort'): move the balance off the account, or "
            "record it with `conductor.cli exclude-balance`. It never clears itself."
        )
