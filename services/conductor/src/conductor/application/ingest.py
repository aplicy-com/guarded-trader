"""Ingest use case: poll Freqtrade (read-only) and upsert trades idempotently."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import structlog

from conductor.application.capital import PrincipalNotSetError, record_snapshot
from conductor.application.ledger_ports import Ledger
from conductor.application.ports import FreqtradeReader
from conductor.domain.ledger import LedgerTrade, from_closed, from_open

log = structlog.get_logger()
Clock = Callable[[], datetime]

PAGE_SIZE = 500
MAX_PAGES = 1000  # safety valve against a misbehaving pagination contract


@dataclass(frozen=True, slots=True)
class FreqtradeInstance:
    name: str
    reader: FreqtradeReader


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


def run_ingest(ledger: Ledger, instances: list[FreqtradeInstance], *, now: Clock) -> IngestReport:
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
            with ledger.transaction() as repo:
                for trade in fetched.trades:
                    counts[repo.upsert_trade(inst.name, trade, now())] += 1
        except Exception:
            log.exception("ingest_instance_failed", instance=inst.name)
            failed.append(inst.name)
            unrealized_total = None
            continue
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
