"""R5 use case: startup balance check against the pair whitelist (live mode only)."""

from collections.abc import Callable
from datetime import datetime

import structlog

from conductor.application.ingest import FreqtradeInstance
from conductor.application.ledger_ports import Ledger
from conductor.application.ports import Notifier
from conductor.domain.isolation import (
    AccountIsolationError,
    IsolationViolation,
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
    for. Any failure to obtain the data also aborts: we never trade unverified.
    The ledger must be freshly ingested first (the caller does that).
    """
    if mode is not TradingMode.LIVE:
        log.info("isolation_check_skipped", reason="not live", trading_mode=mode.value)
        return ()

    with ledger.transaction(write=False) as repo:
        holdings = repo.open_holdings()
    violations: list[IsolationViolation] = []
    for inst in instances:
        try:
            whitelist = inst.reader.whitelist()
            balances = inst.reader.balances()
        except Exception as exc:
            raise IsolationCheckUnavailableError(
                f"cannot verify account isolation for instance {inst.name!r}"
            ) from exc
        violations.extend(check_account_isolation(whitelist, balances, holdings))
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
