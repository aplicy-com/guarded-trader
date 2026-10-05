"""Wire format of the Freqtrade REST API (only the fields Conductor uses).

`extra="ignore"` so new Freqtrade fields never break us; a *missing or
retyped* field we depend on does, loudly, in the contract test and at runtime.
"""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from conductor.domain.freqtrade_view import (
    BotConfigView,
    OpenTradeView,
    ProfitSummary,
    TradesPage,
    TradeView,
)


def _ts(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class PingWire(_Wire):
    status: str


class ShowConfigWire(_Wire):
    bot_name: str
    version: str
    strategy: str | None = None
    dry_run: bool
    trading_mode: str
    stake_currency: str
    stake_amount: Decimal | str
    max_open_trades: int
    timeframe: str
    exchange: str
    state: str = ""

    def to_view(self) -> BotConfigView:
        return BotConfigView(
            bot_name=self.bot_name,
            version=self.version,
            strategy=self.strategy or "",
            dry_run=self.dry_run,
            trading_mode=self.trading_mode,
            stake_currency=self.stake_currency,
            stake_amount=str(self.stake_amount),
            max_open_trades=self.max_open_trades,
            timeframe=self.timeframe,
            exchange=self.exchange,
            state=self.state,
        )


class OpenTradeWire(_Wire):
    trade_id: int
    pair: str
    is_short: bool = False
    open_timestamp: int
    open_rate: Decimal
    amount: Decimal
    stake_amount: Decimal
    current_rate: Decimal | None = None
    profit_abs: Decimal | None = None
    profit_ratio: Decimal | None = None
    has_open_orders: bool = False

    def to_view(self) -> OpenTradeView:
        return OpenTradeView(
            trade_id=self.trade_id,
            pair=self.pair,
            is_short=self.is_short,
            open_date=_ts(self.open_timestamp),
            open_rate=self.open_rate,
            amount=self.amount,
            stake_amount=self.stake_amount,
            current_rate=self.current_rate,
            profit_abs=self.profit_abs,
            profit_ratio=self.profit_ratio,
            has_open_orders=self.has_open_orders,
        )


class TradeWire(_Wire):
    trade_id: int
    pair: str
    is_open: bool
    is_short: bool = False
    open_timestamp: int
    close_timestamp: int | None = None
    open_rate: Decimal
    close_rate: Decimal | None = None
    amount: Decimal
    stake_amount: Decimal
    close_profit_abs: Decimal | None = None
    close_profit: Decimal | None = None  # ratio, e.g. 0.0123 == 1.23%
    fee_open_cost: Decimal | None = None
    fee_close_cost: Decimal | None = None
    exit_reason: str | None = None

    def to_view(self) -> TradeView:
        return TradeView(
            trade_id=self.trade_id,
            pair=self.pair,
            is_open=self.is_open,
            is_short=self.is_short,
            open_date=_ts(self.open_timestamp),
            close_date=_ts(self.close_timestamp) if self.close_timestamp is not None else None,
            open_rate=self.open_rate,
            close_rate=self.close_rate,
            amount=self.amount,
            stake_amount=self.stake_amount,
            close_profit_abs=self.close_profit_abs,
            close_profit_ratio=self.close_profit,
            fee_open_cost=self.fee_open_cost,
            fee_close_cost=self.fee_close_cost,
            exit_reason=self.exit_reason,
        )


class TradesWire(_Wire):
    trades: list[TradeWire]
    trades_count: int
    total_trades: int
    offset: int

    def to_view(self) -> TradesPage:
        return TradesPage(
            trades=tuple(t.to_view() for t in self.trades),
            trades_count=self.trades_count,
            total_trades=self.total_trades,
            offset=self.offset,
        )


class ProfitWire(_Wire):
    profit_closed_coin: Decimal
    profit_closed_ratio: Decimal | None = None
    profit_all_coin: Decimal
    trade_count: int
    closed_trade_count: int
    winning_trades: int
    losing_trades: int
    max_drawdown_abs: Decimal | None = None

    def to_view(self) -> ProfitSummary:
        return ProfitSummary(
            closed_profit_abs=self.profit_closed_coin,
            closed_profit_ratio=self.profit_closed_ratio,
            all_profit_abs=self.profit_all_coin,
            trade_count=self.trade_count,
            closed_trade_count=self.closed_trade_count,
            winning_trades=self.winning_trades,
            losing_trades=self.losing_trades,
            max_drawdown_abs=self.max_drawdown_abs,
        )


class BalanceCurrencyWire(_Wire):
    currency: str
    balance: Decimal  # total held on the exchange (free + used)


class BalanceWire(_Wire):
    currencies: list[BalanceCurrencyWire]

    def to_view(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for c in self.currencies:
            out[c.currency] = out.get(c.currency, Decimal(0)) + c.balance
        return out


class WhitelistWire(_Wire):
    whitelist: list[str]
