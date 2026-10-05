"""R5 use cases: the startup balance check (live only) and the operator's exclusion record."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import structlog

from conductor.application.ingest import FreqtradeInstance
from conductor.application.ledger_ports import Ledger
from conductor.application.ports import Notifier
from conductor.domain.isolation import (
    ZERO,
    AccountIsolationError,
    IsolationViolation,
    base_asset,
    check_account_isolation,
)
from conductor.domain.trading_mode import TradingMode

log = structlog.get_logger()


class IsolationCheckUnavailableError(RuntimeError):
    """The check could not be performed. Fails closed: startup must not proceed."""


def run_startup_isolation_check(
    mode: TradingMode,
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    *,
    notifier: Notifier,
    now: Callable[[], datetime],
) -> tuple[IsolationViolation, ...]:
    """Abort (raise) if a whitelisted pair holds a balance the system did not buy.

    dry_run: a logged no-op (the simulated wallet says nothing about the real
    account). live: for each instance, compare the exchange balance of every
    whitelisted base asset with what the ledger's own open positions account
    for, plus whatever the operator has explicitly excluded. Any failure to obtain
    the data also aborts: we never trade unverified.
    The ledger must be freshly ingested first (the caller does that).
    """
    if mode is not TradingMode.LIVE:
        log.info("isolation_check_skipped", reason="not live", trading_mode=mode.value)
        return ()

    with ledger.transaction(write=False) as repo:
        holdings = repo.open_holdings()
        excluded = repo.exclusions()
    violations: list[IsolationViolation] = []
    for inst in instances:
        try:
            whitelist = inst.reader.whitelist()
            balances = inst.reader.balances()
        except Exception as exc:
            raise IsolationCheckUnavailableError(
                f"cannot verify account isolation for instance {inst.name!r}"
            ) from exc
        violations.extend(check_account_isolation(whitelist, balances, holdings, excluded))
    if not violations:
        log.info("isolation_check_passed", instances=[i.name for i in instances])
        return ()

    error = AccountIsolationError(tuple(violations))
    with ledger.transaction() as repo:
        repo.add_audit(
            now(),
            "system",
            "isolation_violation",
            {"violations": [f"{v.pair}:{v.unexplained}" for v in violations]},
        )
    log.error("isolation_check_failed", error=str(error))
    try:
        notifier.send(f"REFUSING TO START (R5): {error}")
    except Exception:
        log.exception("isolation_alert_failed")
    raise error


# ---- operator side: look at the account, record an exclusion -------------------------------


@dataclass(frozen=True, slots=True)
class IsolationRow:
    asset: str
    exchange_balance: Decimal
    ledger_holding: Decimal
    excluded: Decimal

    @property
    def unexplained(self) -> Decimal:
        return self.exchange_balance - self.ledger_holding - self.excluded


def isolation_rows(ledger: Ledger, instance: FreqtradeInstance) -> list[IsolationRow]:
    """One row per whitelisted base asset (AC5.5: each judged alone). Raises if unreadable."""
    with ledger.transaction(write=False) as repo:
        holdings = repo.open_holdings()
        excluded = repo.exclusions()
    whitelist = instance.reader.whitelist()
    balances = instance.reader.balances()
    assets = sorted({base_asset(p) for p in whitelist})
    return [
        IsolationRow(a, balances.get(a, ZERO), holdings.get(a, ZERO), excluded.get(a, ZERO))
        for a in assets
    ]


class ExclusionError(ValueError):
    """The requested exclusion is not something the account actually holds."""


def record_exclusion(
    ledger: Ledger,
    instance: FreqtradeInstance,
    *,
    asset: str,
    amount: Decimal | None,
    operator: str,
    note: str | None,
    now: Callable[[], datetime],
) -> Decimal:
    """AC5.4: declare ``amount`` of ``asset`` as pre-existing (not the system's).

    ``amount=None`` means "exactly what is unexplained right now". The new amount is the TOTAL
    excluded for the asset (it replaces the previous declaration). It may not exceed what the
    account holds beyond the system's own positions: excluding more than exists would mask a
    future unexplained balance. Returns the amount recorded.
    """
    asset = asset.strip().upper()
    if not asset or not operator.strip():
        raise ExclusionError("asset and operator are required")
    balances = instance.reader.balances()  # raises if unreadable: never record blind
    with ledger.transaction() as repo:
        held = repo.open_holdings().get(asset, ZERO)
        current = repo.exclusions().get(asset, ZERO)
        available = balances.get(asset, ZERO) - held
        total = available if amount is None else amount
        if total < ZERO or not total.is_finite():
            raise ExclusionError("amount must be a finite number >= 0")
        if total > available:
            raise ExclusionError(
                f"cannot exclude {total} {asset}: the account holds {balances.get(asset, ZERO)} "
                f"and the system's own open positions account for {held}"
            )
        repo.add_exclusion(asset, total, now(), operator.strip(), note)
        repo.add_audit(
            now(),
            f"operator:{operator.strip()}",
            "isolation_exclusion_recorded",
            {"asset": asset, "amount": str(total), "previous": str(current), "note": note},
        )
    log.warning("isolation_exclusion_recorded", asset=asset, amount=str(total), operator=operator)
    return total
