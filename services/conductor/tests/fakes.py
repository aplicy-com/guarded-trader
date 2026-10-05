"""Test doubles and builders shared by the ledger tests."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from conductor.application.ledger_ports import FxUnavailableError
from conductor.domain.freqtrade_view import BotConfigView, OpenTradeView, TradesPage, TradeView
from conductor.domain.tax import FxRate

D = Decimal


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@dataclass
class FakeFreqtrade:
    """In-memory FreqtradeReader. Set `fail` to simulate an unreachable instance."""

    open_trades: list[OpenTradeView] = field(default_factory=list)
    closed_trades: list[TradeView] = field(default_factory=list)
    balance_by_currency: dict[str, Decimal] = field(default_factory=dict)
    pairs: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
    fail: bool = False
    calls: list[str] = field(default_factory=list)
    # --- control surface (doubles as the FreqtradeController) ---
    state: str = "running"
    control_fail: bool = False
    exit_works: bool = True  # False: force_exit_all is accepted but nothing closes
    control_calls: list[str] = field(default_factory=list)

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.fail:
            raise ConnectionError("freqtrade unreachable")

    def ping(self) -> bool:
        return not self.fail

    def show_config(self) -> BotConfigView:
        self._check("show_config")
        return BotConfigView(
            "bot", "2026.8", "S", True, "spot", "USD", "unlimited", 2, "4h", "kraken", self.state
        )

    def _ctl(self, name: str) -> None:
        self.control_calls.append(name)
        if self.control_fail or self.fail:
            raise ConnectionError("freqtrade control unreachable")

    def pause_entries(self) -> None:
        self._ctl("pause_entries")
        if self.state == "running":
            self.state = "paused"

    def resume(self) -> None:
        self._ctl("resume")
        self.state = "running"

    def stop(self) -> None:
        self._ctl("stop")
        self.state = "stopped"

    def cancel_open_order(self, trade_id: int) -> None:
        self._ctl(f"cancel:{trade_id}")

    def force_exit_all(self) -> None:
        self._ctl("force_exit_all")
        if self.exit_works:
            self.open_trades = []

    def status(self) -> tuple[OpenTradeView, ...]:
        self._check("status")
        return tuple(self.open_trades)

    def trades(self, *, limit: int = 500, offset: int = 0) -> TradesPage:
        self._check("trades")
        chunk = self.closed_trades[offset : offset + limit]
        return TradesPage(tuple(chunk), len(chunk), len(self.closed_trades), offset)

    def profit(self) -> Any:
        raise NotImplementedError

    def balances(self) -> Mapping[str, Decimal]:
        self._check("balances")
        return dict(self.balance_by_currency)

    def whitelist(self) -> tuple[str, ...]:
        self._check("whitelist")
        return self.pairs


class FakeFx:
    """Deterministic provider: weekends resolve to the prior Friday like the real Bank."""

    def __init__(self) -> None:
        self.calls: list[date] = []
        self.unavailable = False

    def usd_cad(self, on: date) -> FxRate:
        self.calls.append(on)
        if self.unavailable:
            raise FxUnavailableError("down")
        rate_date = on
        while rate_date.weekday() >= 5:
            rate_date = date.fromordinal(rate_date.toordinal() - 1)
        return FxRate(on, rate_date, D("1.40"), "BankOfCanada")


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


def open_view(
    trade_id: int, pair: str = "ETH/USD", amount: str = "0.01", **kw: Any
) -> OpenTradeView:
    base: dict[str, Any] = {
        "trade_id": trade_id,
        "pair": pair,
        "is_short": False,
        "open_date": datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
        "open_rate": D("2500"),
        "amount": D(amount),
        "stake_amount": D("25"),
        "current_rate": D("2600"),
        "profit_abs": D("1.0"),
        "profit_ratio": D("0.04"),
    }
    return OpenTradeView(**{**base, **kw})


def closed_view(trade_id: int, profit: str = "2.00", pair: str = "ETH/USD", **kw: Any) -> TradeView:
    base: dict[str, Any] = {
        "trade_id": trade_id,
        "pair": pair,
        "is_open": False,
        "is_short": False,
        "open_date": datetime(2026, 9, 11, 16, 10, tzinfo=UTC),
        "close_date": datetime(2026, 9, 14, 9, 24, tzinfo=UTC),
        "open_rate": D("2573.74"),
        "close_rate": D("2477.5"),
        "amount": D("0.0128218"),
        "stake_amount": D("33.0"),
        "close_profit_abs": D(profit),
        "close_profit_ratio": D("0.01"),
        "fee_open_cost": D("0.05"),
        "fee_close_cost": D("0.08"),
        "exit_reason": "roi",
    }
    return TradeView(**{**base, **kw})


class BrokenNotifier:
    """A notifier that always fails: alerts are best-effort, risk logic must not care."""

    def __init__(self) -> None:
        self.attempts = 0

    def send(self, text: str) -> None:
        self.attempts += 1
        raise RuntimeError("telegram is down")
