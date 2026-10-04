"""NFR6 use cases: CAD fair value per closed trade, and the tax CSV export.

Records fair values only; no tax treatment is assumed (docs/09-tax-questions.md).
"""

import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TextIO

import structlog

from conductor.application.ledger_ports import FxRateProvider, FxUnavailableError, Ledger
from conductor.domain.tax import FxRate, value_closed_trade

log = structlog.get_logger()
Clock = Callable[[], datetime]

CSV_COLUMNS = (
    "instance",
    "trade_id",
    "pair",
    "open_date_utc",
    "close_date_utc",
    "amount",
    "exit_reason",
    "cost_usd",
    "net_proceeds_usd",
    "profit_usd",
    "open_fx_rate_date",
    "open_usd_cad",
    "close_fx_rate_date",
    "close_usd_cad",
    "cost_cad",
    "proceeds_cad",
    "gain_cad",
    "fx_source",
)


@dataclass(frozen=True, slots=True)
class ValuationReport:
    valued: int
    pending: int  # closed today (UTC): the day's rate is not final yet
    failed: int  # missing data or no FX rate; retried on the next run


def value_closed_trades(ledger: Ledger, fx: FxRateProvider, *, now: Clock) -> ValuationReport:
    """Value every closed, not-yet-valued trade. Idempotent; failures are isolated.

    A trade is valued only once its close day (UTC) is over, so the published
    daily rate for that day exists. Missing fee/profit data or an unavailable
    rate leaves the trade unvalued (never guessed) and it is retried later.
    """
    today = now().date()
    with ledger.transaction(write=False) as repo:
        todo = repo.unvalued_closed_trades()
    memo: dict[date, FxRate] = {}

    def rate_for(day: date) -> FxRate:
        if day in memo:
            return memo[day]
        with ledger.transaction(write=False) as repo:
            cached = repo.get_fx(day)
        if cached is None:
            cached = fx.usd_cad(day)
            with ledger.transaction() as repo:
                repo.put_fx(cached, now())
        memo[day] = cached
        return cached

    valued = pending = failed = 0
    for tr in todo:
        if tr.close_date.date() >= today:
            pending += 1
            continue
        if tr.fee_open_cost is None or tr.close_profit_abs is None:
            log.error("valuation_incomplete_trade", instance=tr.instance, trade_id=tr.ft_trade_id)
            failed += 1
            continue
        try:
            valuation = value_closed_trade(
                stake_usd=tr.stake_amount,
                fee_open_usd=tr.fee_open_cost,
                close_profit_usd=tr.close_profit_abs,
                open_fx=rate_for(tr.open_date.date()),
                close_fx=rate_for(tr.close_date.date()),
            )
            with ledger.transaction() as repo:
                repo.save_valuation(tr.trade_pk, valuation, now())
        except FxUnavailableError:
            log.warning("valuation_fx_unavailable", instance=tr.instance, trade_id=tr.ft_trade_id)
            failed += 1
        except Exception:
            log.exception("valuation_failed", instance=tr.instance, trade_id=tr.ft_trade_id)
            failed += 1
        else:
            valued += 1
    log.info("valuation_done", valued=valued, pending=pending, failed=failed)
    return ValuationReport(valued, pending, failed)


def _plain(value: Decimal) -> str:
    return format(value, "f")


def _text(value: str | None) -> str:
    """Neutralise spreadsheet formula injection in free-text cells."""
    if value and value[0] in "=+-@\t\r":
        return "'" + value
    return value or ""


def export_tax_csv(ledger: Ledger, out: TextIO) -> int:
    """Write one CSV row per valued closed trade; returns the row count."""
    with ledger.transaction(write=False) as repo:
        rows = repo.tax_rows()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        v = r.valuation
        writer.writerow(
            [
                _text(r.instance),
                r.ft_trade_id,
                _text(r.pair),
                r.open_date.isoformat(timespec="seconds"),
                r.close_date.isoformat(timespec="seconds"),
                _plain(r.amount),
                _text(r.exit_reason),
                _plain(v.cost_usd),
                _plain(v.net_proceeds_usd),
                _plain(v.net_proceeds_usd - v.cost_usd),
                v.open_fx.rate_date.isoformat(),
                _plain(v.open_fx.rate),
                v.close_fx.rate_date.isoformat(),
                _plain(v.close_fx.rate),
                _plain(v.cost_cad),
                _plain(v.proceeds_cad),
                _plain(v.gain_cad),
                v.close_fx.source,
            ]
        )
    return len(rows)
