"""Ledger trade record and the idempotent merge rule. Pure; no I/O."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from conductor.domain.freqtrade_view import OpenTradeView, TradeView


@dataclass(frozen=True, slots=True)
class LedgerTrade:
    ft_trade_id: int
    pair: str
    is_open: bool
    is_short: bool
    open_date: datetime
    close_date: datetime | None
    open_rate: Decimal
    close_rate: Decimal | None
    amount: Decimal
    stake_amount: Decimal
    fee_open_cost: Decimal | None
    fee_close_cost: Decimal | None
    close_profit_abs: Decimal | None
    exit_reason: str | None


def from_closed(t: TradeView) -> LedgerTrade:
    return LedgerTrade(
        ft_trade_id=t.trade_id,
        pair=t.pair,
        is_open=t.is_open,
        is_short=t.is_short,
        open_date=t.open_date,
        close_date=t.close_date,
        open_rate=t.open_rate,
        close_rate=t.close_rate,
        amount=t.amount,
        stake_amount=t.stake_amount,
        fee_open_cost=t.fee_open_cost,
        fee_close_cost=t.fee_close_cost,
        close_profit_abs=t.close_profit_abs,
        exit_reason=t.exit_reason,
    )


def from_open(t: OpenTradeView) -> LedgerTrade:
    return LedgerTrade(
        ft_trade_id=t.trade_id,
        pair=t.pair,
        is_open=True,
        is_short=t.is_short,
        open_date=t.open_date,
        close_date=None,
        open_rate=t.open_rate,
        close_rate=None,
        amount=t.amount,
        stake_amount=t.stake_amount,
        fee_open_cost=None,
        fee_close_cost=None,
        close_profit_abs=None,
        exit_reason=None,
    )


def merge_trade(existing: LedgerTrade | None, incoming: LedgerTrade) -> LedgerTrade:
    """Result of upserting ``incoming`` over ``existing``; idempotent.

    - No existing row: incoming as-is.
    - A closed trade is final: a stale "open" snapshot never reopens it, and an
      identical closed re-ingest changes nothing.
    - open -> closed: the closed record wins.
    - open -> open: incoming wins, but fees the open snapshot cannot know are kept.
    """
    if existing is None:
        return incoming
    if not existing.is_open:
        return incoming if not incoming.is_open else existing
    if not incoming.is_open:
        return incoming
    return replace(
        incoming,
        fee_open_cost=incoming.fee_open_cost
        if incoming.fee_open_cost is not None
        else existing.fee_open_cost,
    )
