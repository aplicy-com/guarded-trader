"""R3 use cases: the daily UTC fence run (ledger-only) and manual transfer recording."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import structlog

from conductor.application.capital import capital_from_ledger, record_snapshot
from conductor.application.ledger_ports import Ledger, TransferRecord
from conductor.application.notify import safe_send
from conductor.application.ports import Notifier
from conductor.domain.fence import (
    MoveDue,
    manual_move_due,
    missed_fence_days,
    plan_fence,
    validate_transfer,
)

log = structlog.get_logger()
Clock = Callable[[], datetime]
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class FenceReport:
    fence_date: date
    ran: bool  # False: today's run already exists (nothing written)
    fenced_amount: Decimal
    missed_days: tuple[date, ...]
    cap_configured: bool
    move_due: MoveDue


def _utc_now(now: Clock) -> datetime:
    value = now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def run_daily_fence(
    ledger: Ledger,
    *,
    daily_profit_cap: Decimal | None,
    manual_move_threshold: Decimal,
    now: Clock,
    notifier: Notifier | None = None,
) -> FenceReport:
    """Fence working profit above ``daily_profit_cap``. No exchange call, ever.

    Safe to run any number of times per UTC day (one run is recorded per day)
    and safe after downtime: the fence works on cumulative working profit, so a
    missed day is caught up on the next run, and the gap is logged/audited
    (AC3.6). With no cap configured (value TBD, Phase 3) nothing is fenced and a
    warning is logged: profit then stays working profit (AC2.4).
    """
    at = _utc_now(now)
    today = at.date()
    with ledger.transaction() as repo:
        last = repo.last_fence_date()
        missed = missed_fence_days(last, today)
        cap_ok = daily_profit_cap is not None
        cap = capital_from_ledger(repo)
        fenced = (
            plan_fence(cap.working_profit, daily_profit_cap)
            if daily_profit_cap is not None
            else ZERO
        )

        ran = repo.add_fence_event(
            fence_date=today,
            ran_at=at,
            daily_profit_cap=daily_profit_cap,
            working_profit_before=cap.working_profit,
            fenced_amount=fenced,
            missed_days=len(missed),
        )
        if ran:
            repo.add_audit(
                at,
                "system",
                "fence_run",
                {
                    "fence_date": today.isoformat(),
                    "working_profit_before": str(cap.working_profit),
                    "daily_profit_cap": None if daily_profit_cap is None else str(daily_profit_cap),
                    "fenced_amount": str(fenced),
                    "missed_days": [d.isoformat() for d in missed],
                },
            )
            if missed:
                repo.add_audit(
                    at, "system", "fence_run_missed", {"days": [d.isoformat() for d in missed]}
                )
            # AC2.1: capital is re-derived immediately after every fencing event.
            previous = repo.latest_snapshot()
            record_snapshot(repo, at, previous.unrealized_profit if previous else None)
        else:
            fenced = ZERO

        fenced_total = repo.fenced_total()
        due = manual_move_due(
            fenced_total=fenced_total,
            moved_total=repo.moved_total(),
            threshold=manual_move_threshold,
            now=at,
            since=repo.last_transfer_at() or repo.first_positive_fence_at(),
        )

    if not cap_ok:
        log.warning(
            "fence_cap_not_configured", note="daily_profit_cap is TBD (Phase 3); nothing fenced"
        )
    if missed:
        log.warning("fence_run_missed", days=[d.isoformat() for d in missed])
    if ran:
        log.info("fence_run", fence_date=today.isoformat(), fenced_amount=str(fenced))
    if ran:  # one alert set per UTC day, not one per restart
        if fenced > ZERO:
            safe_send(
                notifier,
                f"FENCED {fenced:.2f} USD of profit (fence run {today.isoformat()}); "
                f"max deployed capital is now {cap.max_deployed_capital - fenced:.2f} USD",
            )
        if missed:
            safe_send(
                notifier,
                f"Fence run MISSED for {len(missed)} UTC day(s): "
                + ", ".join(d.isoformat() for d in missed)
                + " (caught up now)",
            )
        if due.due:
            why = "over threshold" if due.over_threshold else "30 days since last move"
            safe_send(
                notifier,
                f"MANUAL MOVE DUE: {due.unmoved:.2f} USD fenced and not yet moved "
                f"({why}). Move it by hand on Kraken, then record it.",
            )
    if due.due:
        # Alerting arrives in 3A-4; for now this is a log line. The system never moves funds.
        log.warning(
            "manual_move_due",
            unmoved=str(due.unmoved),
            over_threshold=due.over_threshold,
            month_elapsed=due.month_elapsed,
        )
    return FenceReport(today, ran, fenced, missed, cap_ok, due)


def record_manual_transfer(
    ledger: Ledger,
    *,
    amount: Decimal,
    destination: str,
    exchange_tx_id: str,
    transferred_at: datetime,
    operator: str,
    note: str | None = None,
    now: Clock,
) -> TransferRecord:
    """Record a transfer the operator already made by hand (AC3.5). Records only.

    Validated inside the write transaction against fenced-but-unmoved profit.
    """
    for label, value in (
        ("destination", destination),
        ("exchange_tx_id", exchange_tx_id),
        ("operator", operator),
    ):
        if not value.strip():
            raise ValueError(f"{label} must not be empty")
    if transferred_at.tzinfo is None or transferred_at.utcoffset() is None:
        raise ValueError("transferred_at must be timezone-aware")
    at = _utc_now(now)
    if transferred_at > at:
        raise ValueError("transferred_at is in the future")
    record = TransferRecord(
        amount=amount,
        destination=destination.strip(),
        exchange_tx_id=exchange_tx_id.strip(),
        transferred_at=transferred_at,
        operator=operator.strip(),
        note=note,
    )
    with ledger.transaction() as repo:
        validate_transfer(amount, repo.fenced_total(), repo.moved_total())
        repo.add_transfer(record, at)
        repo.add_audit(
            at,
            record.operator,
            "manual_transfer_recorded",
            {
                "amount": str(amount),
                "destination": record.destination,
                "exchange_tx_id": record.exchange_tx_id,
            },
        )
    log.info("manual_transfer_recorded", amount=str(amount), operator=record.operator)
    return record
