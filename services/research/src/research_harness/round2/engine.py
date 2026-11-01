"""Daily long-or-flat portfolio backtester for round 2. Pure; no I/O.

Conventions (frozen in services/research/candidates-round2.json, ``execution``):
- A decision is taken at the close of a check day from data up to and including that day, and
  filled at the next day's open. Sells before buys. A decision on the last day is discarded.
- A fill of notional ``n`` moves cash by ``n * (1 + c)`` (buy) or ``n * (1 - c)`` (sell), ``c``
  the per-fill cost (fee + slippage): Freqtrade's spot fee model.
- Weights are fractions of equity in [0, 1]; at most one pair is held at a time (one slot).
- The backtest starts flat; a position still open after the last day is closed at that day's
  close and tagged ``force_exit``.

Output trades use Freqtrade's backtest trade-row shape (``orders`` with ``amount``,
``safe_price``, ``ft_is_entry``, ``ft_order_side``, ``order_filled_timestamp``), so the
harness's own ``metrics.compute_metrics`` scores them exactly as it scores Freqtrade runs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FORCE_EXIT = "force_exit"
EXIT_SIGNAL = "exit_signal"
EPS = 1e-12

# decide(i, held_pair_or_None, current_weight_of_held) -> target {pair: weight} or None (no trade)
Decide = Callable[[int, str | None, float], dict[str, float] | None]


@dataclass(frozen=True)
class Market:
    """Calendar-day grid shared by every pair; NaN before a pair's first candle."""

    dates: pd.DatetimeIndex
    open: Mapping[str, np.ndarray]
    close: Mapping[str, np.ndarray]

    @classmethod
    def from_panel(cls, panel: Mapping[str, pd.DataFrame]) -> Market:
        start = min(df.index[0] for df in panel.values())
        end = max(df.index[-1] for df in panel.values())
        dates = pd.date_range(start, end, freq="D", tz="UTC")
        o = {p: df["open"].reindex(dates).to_numpy(float) for p, df in panel.items()}
        c = {p: df["close"].reindex(dates).to_numpy(float) for p, df in panel.items()}
        return cls(dates, o, c)

    @property
    def pairs(self) -> tuple[str, ...]:
        return tuple(self.close)

    def index_of(self, ts: pd.Timestamp) -> int:
        return int(self.dates.get_loc(ts))

    def closes_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.close, index=self.dates)


@dataclass
class FillRecord:
    pair: str
    day: int
    side: str  # buy | sell
    amount: float
    price: float
    notional: float
    equity_before: float  # account value at the fill price, just before the fill
    force_exit: bool = False

    @property
    def turnover(self) -> float:
        return self.notional / self.equity_before if self.equity_before > 0 else 0.0


@dataclass
class SimResult:
    start: int
    end: int  # exclusive
    cost: float
    starting_balance: float
    equity: np.ndarray  # at each day's close, days start..end-1, force exit included
    fills: list[FillRecord] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    decisions: dict[int, str | None] = field(default_factory=dict)  # check day -> state after it
    targets: dict[int, dict[str, float]] = field(default_factory=dict)  # check day -> target sent

    def equity_series(self, dates: pd.DatetimeIndex) -> pd.Series:
        return pd.Series(self.equity, index=dates[self.start : self.end], name="equity")


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 1_000_000)


class _Book:
    def __init__(self, market: Market, cost: float, balance: float) -> None:
        self.m, self.c = market, cost
        self.cash = balance
        self.units: dict[str, float] = {}
        self.open_trade: dict[str, dict] = {}
        self.fills: list[FillRecord] = []
        self.trades: list[dict] = []

    def value(self, prices: Mapping[str, float]) -> float:
        return self.cash + sum(u * prices[p] for p, u in self.units.items() if u > EPS)

    def _order(self, pair: str, day: int, side: str, amount: float, price: float, eq: float, forced: bool) -> None:
        notional = amount * price
        if side == "buy":
            self.cash -= notional * (1 + self.c)
            self.units[pair] = self.units.get(pair, 0.0) + amount
        else:
            self.cash += notional * (1 - self.c)
            self.units[pair] = self.units.get(pair, 0.0) - amount
            if self.units[pair] < EPS:
                self.units[pair] = 0.0
        self.fills.append(FillRecord(pair, day, side, amount, price, notional, eq, forced))
        ts = self.m.dates[day]
        t = self.open_trade.get(pair)
        if t is None:
            t = {"pair": pair, "open_date": str(ts), "orders": [], "fee_open": self.c, "fee_close": self.c, "_net": 0.0}
            self.open_trade[pair] = t
        t["orders"].append(
            {
                "amount": amount,
                "safe_price": price,
                "ft_is_entry": side == "buy",
                "ft_order_side": side,
                "order_filled_timestamp": _ms(ts),
            }
        )
        t["_net"] += notional * (1 - self.c) if side == "sell" else -notional * (1 + self.c)
        if side == "sell" and self.units[pair] == 0.0:
            t["close_date"] = str(ts)
            t["exit_reason"] = FORCE_EXIT if forced else EXIT_SIGNAL
            t["profit_abs"] = t.pop("_net")
            self.trades.append(self.open_trade.pop(pair))

    def rebalance(
        self, day: int, target: Mapping[str, float], prices: Mapping[str, float], forced: bool = False
    ) -> None:
        eq = self.value(prices)
        # sells first
        for pair, u in list(self.units.items()):
            if u <= EPS:
                continue
            want = target.get(pair, 0.0)
            have = u * prices[pair]
            if want <= EPS:
                self._order(pair, day, "sell", u, prices[pair], eq, forced)
            elif have > want * eq + EPS:
                self._order(pair, day, "sell", (have - want * eq) / prices[pair], prices[pair], eq, forced)
        for pair, w in target.items():
            if w <= EPS:
                continue
            have = self.units.get(pair, 0.0) * prices[pair]
            need = w * eq - have
            if need > EPS:
                n = min(need, self.cash / (1 + self.c))
                if n > EPS:
                    self._order(pair, day, "buy", n / prices[pair], prices[pair], eq, forced)


def simulate(
    market: Market,
    decide: Decide,
    is_check_day: Callable[[int], bool],
    start: int,
    end: int,
    cost: float,
    balance: float,
    initial_target: Mapping[str, float] | None = None,
) -> SimResult:
    """Run days ``start``..``end - 1``. ``initial_target`` (benchmark only) fills at the first open."""
    book = _Book(market, cost, balance)
    equity = np.empty(end - start)
    pending: Mapping[str, float] | None = initial_target
    decisions: dict[int, str | None] = {}
    targets: dict[int, dict[str, float]] = {}
    held_state: str | None = None
    for k, i in enumerate(range(start, end)):
        if pending is not None:
            book.rebalance(i, pending, {p: market.open[p][i] for p in market.pairs})
            pending = None
        closes = {p: market.close[p][i] for p in market.pairs}
        if i < end - 1 and is_check_day(i):
            held = next((p for p, u in book.units.items() if u > EPS), None)
            w = book.units[held] * closes[held] / book.value(closes) if held else 0.0
            target = decide(i, held, w)
            if target is not None:
                pending = target
                targets[i] = dict(target)
                held_state = next((p for p, x in target.items() if x > EPS), None)
            else:
                held_state = held
            decisions[i] = held_state
        if i == end - 1 and any(u > EPS for u in book.units.values()):
            book.rebalance(i, {}, closes, forced=True)
        equity[k] = book.value(closes)
    return SimResult(start, end, cost, balance, equity, book.fills, book.trades, decisions, targets)


def round_trips_per_year(fills: list[FillRecord], dates: pd.DatetimeIndex) -> dict[int, float]:
    """Notional turnover / 2 per calendar year, force exits excluded."""
    out: dict[int, float] = {}
    for f in fills:
        if f.force_exit:
            continue
        y = dates[f.day].year
        out[y] = out.get(y, 0.0) + f.turnover / 2
    return out
