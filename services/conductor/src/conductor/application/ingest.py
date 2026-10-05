"""Ingest use case: poll Freqtrade (read-only) and upsert trades idempotently."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import structlog

from conductor.application.capital import PrincipalNotSetError, record_snapshot
from conductor.application.ledger_ports import Ledger
from conductor.application.notify import safe_send
from conductor.application.ports import FreqtradeController, FreqtradeReader, Notifier
from conductor.domain.ledger import LedgerTrade, from_closed, from_open

log = structlog.get_logger()
Clock = Callable[[], datetime]

PAGE_SIZE = 500
ALERT_MAX_AGE = timedelta(hours=6)  # never alert on old history (first import, long outage)
MAX_PAGES = 1000  # safety valve against a misbehaving pagination contract


@dataclass(frozen=True, slots=True)
class FreqtradeInstance:
    name: str
    reader: FreqtradeReader
    controller: FreqtradeController | None = None  # write surface; None = read-only


@dataclass(frozen=True, slots=True)
class IngestReport:
    inserted: int
    updated: int
    unchanged: int
    failed_instances: tuple[str, ...]
    snapshot_written: bool


@dataclass(frozen=True, slots=True)
class _Fetched:
    trades: list[LedgerTrade]
    unrealized: Decimal | None


def _fetch(reader: FreqtradeReader) -> _Fetched:
    trades: list[LedgerTrade] = []
    open_views = reader.status()
    unrealized: Decimal | None = Decimal(0)
    for ov in open_views:
        trades.append(from_open(ov))
        unrealized = (
            None if unrealized is None or ov.profit_abs is None else unrealized + ov.profit_abs
        )

    offset = 0
    for _ in range(MAX_PAGES):
        page = reader.trades(limit=PAGE_SIZE, offset=offset)
        for tv in page.trades:
            if not tv.is_open and (tv.close_profit_abs is None or tv.close_date is None):
                raise ValueError(f"closed trade {tv.trade_id} lacks close profit/date")
            trades.append(from_closed(tv))
        offset += len(page.trades)
        if not page.trades or offset >= page.total_trades:
            break
    else:
        raise RuntimeError("trades pagination did not terminate")
    return _Fetched(trades, unrealized)


def _trade_alert(inst: str, trade: LedgerTrade, outcome: str, at: datetime) -> str | None:
    """Alert text for a first-seen open trade or an open->closed transition, if recent."""
    if trade.is_open and outcome == "inserted" and at - trade.open_date <= ALERT_MAX_AGE:
        return (
            f"OPENED {inst} {trade.pair} {trade.amount:f} @ {trade.open_rate:f} "
            f"(stake {trade.stake_amount:.2f} USD)"
        )
    closed_recently = (
        not trade.is_open
        and outcome in ("inserted", "updated")
        and trade.close_date is not None
        and at - trade.close_date <= ALERT_MAX_AGE
    )
    if closed_recently:
        profit = trade.close_profit_abs or Decimal(0)
        return f"CLOSED {inst} {trade.pair} {profit:+.2f} USD ({trade.exit_reason or 'n/a'})"
    return None


def run_ingest(
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    *,
    now: Clock,
    notifier: Notifier | None = None,
) -> IngestReport:
    """Upsert every instance's trades; one unreachable instance never blocks the others.

    Idempotent: re-ingesting the same Freqtrade state changes nothing. A failed
    instance is reported (and its unrealized P&L is unknown for the snapshot).
    """
    counts: Counter[str] = Counter()
    failed: list[str] = []
    unrealized_total: Decimal | None = Decimal(0)
    for inst in instances:
        try:
            fetched = _fetch(inst.reader)
            events: list[str] = []
            with ledger.transaction() as repo:
                for trade in fetched.trades:
                    at = now()
                    outcome = repo.upsert_trade(inst.name, trade, at)
                    counts[outcome] += 1
                    text = _trade_alert(inst.name, trade, outcome, at)
                    if text is not None:
                        events.append(text)
        except Exception:
            log.exception("ingest_instance_failed", instance=inst.name)
            failed.append(inst.name)
            unrealized_total = None
            continue
        for text in events:  # after the commit: alerts follow the ledger, never lead it
            safe_send(notifier, text)
        if unrealized_total is not None:
            unrealized_total = (
                None if fetched.unrealized is None else unrealized_total + fetched.unrealized
            )

    snapshot_written = False
    try:
        with ledger.transaction() as repo:
            snapshot_written = record_snapshot(repo, now(), unrealized_total)
    except PrincipalNotSetError:
        log.error("ingest_snapshot_skipped_no_principal")

    report = IngestReport(
        inserted=counts["inserted"],
        updated=counts["updated"],
        unchanged=counts["unchanged"],
        failed_instances=tuple(failed),
        snapshot_written=snapshot_written,
    )
    log.info(
        "ingest_done",
        inserted=report.inserted,
        updated=report.updated,
        unchanged=report.unchanged,
        failed_instances=list(report.failed_instances),
        snapshot_written=report.snapshot_written,
    )
    return report
