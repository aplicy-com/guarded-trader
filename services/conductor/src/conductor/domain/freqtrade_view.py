"""Conductor's own, framework-free view of what Freqtrade reports.

Read-only snapshots. Money is `Decimal`, time is timezone-aware UTC. The
Freqtrade adapter maps the REST wire format into these; nothing in here knows
about HTTP or JSON.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BotConfigView:
    bot_name: str
    version: str
    strategy: str
    dry_run: bool
    trading_mode: str
    stake_currency: str
    stake_amount: str  # Freqtrade allows the literal "unlimited"
    max_open_trades: int
    timeframe: str
    exchange: str


@dataclass(frozen=True, slots=True)
class OpenTradeView:
    trade_id: int
    pair: str
    is_short: bool
    open_date: datetime
    open_rate: Decimal
    amount: Decimal
    stake_amount: Decimal
    current_rate: Decimal | None
    profit_abs: Decimal | None
    profit_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class TradeView:
    trade_id: int
    pair: str
    is_open: bool
    is_short: bool
    open_date: datetime
    close_date: datetime | None
    open_rate: Decimal
    close_rate: Decimal | None
    amount: Decimal
    stake_amount: Decimal
    close_profit_abs: Decimal | None
    close_profit_ratio: Decimal | None
    fee_open_cost: Decimal | None
    fee_close_cost: Decimal | None
    exit_reason: str | None


@dataclass(frozen=True, slots=True)
class TradesPage:
    trades: tuple[TradeView, ...]
    trades_count: int
    total_trades: int
    offset: int


@dataclass(frozen=True, slots=True)
class ProfitSummary:
    closed_profit_abs: Decimal
    closed_profit_ratio: Decimal | None
    all_profit_abs: Decimal
    trade_count: int
    closed_trade_count: int
    winning_trades: int
    losing_trades: int
    max_drawdown_abs: Decimal | None
