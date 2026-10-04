"""R2 use case (compute only): derive capital from the ledger and snapshot it.

Nothing here talks to Freqtrade; enforcement (writing `available_capital`,
`/reload_config`, `/stopentry`) is not part of 3A-2.
"""

from datetime import datetime
from decimal import Decimal

from conductor.application.ledger_ports import EquitySnapshot, Ledger, LedgerRepo
from conductor.domain.capital import CapitalSnapshot, compute_capital


class PrincipalNotSetError(RuntimeError):
    """The ledger has no principal yet (startup has not run `ensure_principal`)."""


def capital_from_ledger(repo: LedgerRepo) -> CapitalSnapshot:
    principal = repo.get_principal()
    if principal is None:
        raise PrincipalNotSetError("principal is not recorded in the ledger")
    return compute_capital(principal, repo.realized_profit_total(), repo.fenced_total())


def get_capital(ledger: Ledger) -> CapitalSnapshot:
    with ledger.transaction(write=False) as repo:
        return capital_from_ledger(repo)


def record_snapshot(repo: LedgerRepo, now: datetime, unrealized: Decimal | None) -> bool:
    """Append an equity snapshot unless nothing changed since the last one."""
    cap = capital_from_ledger(repo)
    snap = EquitySnapshot(
        taken_at=now,
        principal=cap.principal,
        realized_profit=cap.realized_profit,
        unrealized_profit=unrealized,
        fenced_total=cap.fenced_total,
        working_profit=cap.working_profit,
        max_deployed_capital=cap.max_deployed_capital,
        equity=None if unrealized is None else cap.principal + cap.realized_profit + unrealized,
    )
    last = repo.latest_snapshot()
    if last is not None and last.same_state(snap):
        return False
    repo.add_snapshot(snap)
    return True
