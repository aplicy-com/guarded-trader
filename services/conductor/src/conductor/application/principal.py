"""R1 use case: set the principal once from config; refuse any later mismatch."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import structlog

from conductor.application.ledger_ports import Ledger
from conductor.application.ports import Notifier
from conductor.domain.capital import PrincipalMismatchError, check_principal

log = structlog.get_logger()
Clock = Callable[[], datetime]


def ensure_principal(
    ledger: Ledger,
    configured: Decimal,
    *,
    notifier: Notifier,
    now: Clock,
    currency: str = "USD",
    source: str = "env:PRINCIPAL_USD",
) -> None:
    """First run: record ``configured`` as the (immutable) principal.

    Later runs: no-op if equal; otherwise alert and raise
    :class:`PrincipalMismatchError`. The recorded value is never overwritten
    (the table is append-only at the database level as well).
    """
    mismatch: PrincipalMismatchError | None = None
    with ledger.transaction() as repo:
        recorded = repo.get_principal()
        try:
            needs_record = check_principal(recorded, configured)
        except PrincipalMismatchError as exc:
            mismatch = exc
            repo.add_audit(
                now(),
                "system",
                "principal_mismatch",
                {"configured": str(configured), "recorded": str(recorded)},
            )
        else:
            if needs_record:
                repo.set_principal(configured, currency, now(), source)
                repo.add_audit(
                    now(), "system", "principal_set", {"amount": str(configured), "source": source}
                )
                log.info("principal_set", amount=str(configured), currency=currency)
    if mismatch is not None:
        log.error("principal_mismatch_refusing_start", error=str(mismatch))
        try:
            notifier.send(f"REFUSING TO START (R1): {mismatch}")
        except Exception:
            log.exception("principal_mismatch_alert_failed")
        raise mismatch
