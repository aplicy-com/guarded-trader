"""Startup gate: R1 principal, then (live only) a fresh ingest and the R5 balance check.

Any exception from here means Conductor must not start.
"""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.isolation import (
    IsolationCheckUnavailableError,
    run_startup_isolation_check,
)
from conductor.application.ledger_ports import Ledger
from conductor.application.ports import Notifier
from conductor.application.principal import ensure_principal
from conductor.domain.trading_mode import TradingMode


def run_startup_checks(
    *,
    mode: TradingMode,
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    notifier: Notifier,
    principal: Decimal,
    now: Callable[[], datetime],
) -> None:
    ensure_principal(ledger, principal, notifier=notifier, now=now)
    if mode is TradingMode.LIVE:
        # The ledger must reflect Freqtrade's own positions before comparing balances.
        report = run_ingest(ledger, instances, now=now)
        if report.failed_instances:
            raise IsolationCheckUnavailableError(
                f"ingest failed for {list(report.failed_instances)}; cannot verify isolation"
            )
    run_startup_isolation_check(mode, ledger, instances, notifier=notifier, now=now)
