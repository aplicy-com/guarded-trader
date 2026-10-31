"""Daily mark-to-market equity and the Gate 1 metrics computed from it. Pure; no I/O.

Gate 1 pins Sharpe to the daily-equity basis (docs/08-paper-exit-criteria.md). This module
rebuilds the account from the filled orders and marks every open position to the day's close:
the same idea as Freqtrade's "Sharpe (daily wallet balance)", but computed here so the harness
can exclude force-exit trades (which Freqtrade's figure includes), score walk-forward windows
and null seeds identically, and be unit-tested. The rebuild is checked against Freqtrade's own
final balance on every run (``equity_rebuild_minus_freqtrade`` in the report).

Conventions:
- A day is a UTC calendar day; equity is measured at the day's last close.
- An order filled on day d moves cash and position before day d is marked.
- Cash moves by ``cost * (1 + fee)`` on a buy and ``cost * (1 - fee)`` on a sell, ``cost`` being
  ``amount * price``: Freqtrade's spot fee model.
- Annualisation uses 365 days (crypto trades every day).
- ``force_exit`` trades (closed by the backtester because the data ended) are excluded from
  every headline figure and reported separately (Gate 1 force-exit rule).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365
FORCE_EXIT = "force_exit"


@dataclass(frozen=True, slots=True)
class Fill:
    pair: str
    time: pd.Timestamp  # UTC
    side: str  # "buy" | "sell"
    amount: float
    price: float
    fee_rate: float


@dataclass(frozen=True, slots=True)
class TradeSummary:
    pair: str
    open_date: pd.Timestamp
    close_date: pd.Timestamp
    profit_abs: float  # net of fees
    fees_abs: float
    stake: float  # cost of all entry fills (not Freqtrade's stake_amount, which shrinks on partial exits)
    exit_reason: str
    scale_downs: int  # exit fills before the final one


def fills_from_trades(trades: Iterable[Mapping]) -> list[Fill]:
    """Flatten Freqtrade backtest trade rows (minified ``orders``) into fills."""
    fills: list[Fill] = []
    for t in trades:
        for o in t["orders"]:
            if not o.get("amount") or o.get("order_filled_timestamp") is None:
                continue
            is_entry = bool(o["ft_is_entry"])
            fills.append(
                Fill(
                    pair=t["pair"],
                    time=pd.Timestamp(o["order_filled_timestamp"], unit="ms", tz="UTC"),
                    side=o["ft_order_side"],
                    amount=float(o["amount"]),
                    price=float(o["safe_price"]),
                    fee_rate=float(t["fee_open"] if is_entry else t["fee_close"]),
                )
            )
    return sorted(fills, key=lambda f: f.time)


def summarise_trades(trades: Iterable[Mapping]) -> list[TradeSummary]:
    out = []
    for t in trades:
        filled = [o for o in t["orders"] if o.get("amount") and o.get("order_filled_timestamp") is not None]
        fees = sum(
            float(o["amount"]) * float(o["safe_price"]) * float(t["fee_open"] if o["ft_is_entry"] else t["fee_close"])
            for o in filled
        )
        entry_cost = sum(float(o["amount"]) * float(o["safe_price"]) for o in filled if o["ft_is_entry"])
        exits = sum(1 for o in filled if not o["ft_is_entry"])
        out.append(
            TradeSummary(
                pair=t["pair"],
                open_date=pd.Timestamp(t["open_date"]),
                close_date=pd.Timestamp(t["close_date"]),
                profit_abs=float(t["profit_abs"]),
                fees_abs=fees,
                stake=entry_cost,
                exit_reason=str(t["exit_reason"]),
                scale_downs=max(exits - 1, 0),
            )
        )
    return out


def daily_closes(ohlcv: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """One column per pair: the last close of each UTC day (any candle timeframe)."""
    cols = {}
    for pair, df in ohlcv.items():
        s = df.set_index(pd.to_datetime(df["date"], utc=True))["close"]
        cols[pair] = s.groupby(s.index.floor("D")).last()
    return pd.DataFrame(cols).sort_index()


def daily_equity(
    fills: list[Fill],
    closes: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    starting_balance: float,
) -> pd.Series:
    """Account value at each day's close, from ``start`` to ``end`` inclusive (UTC days)."""
    days = pd.date_range(start.floor("D"), end.floor("D"), freq="D", tz="UTC")
    marks = closes.reindex(days.union(closes.index)).sort_index().ffill().reindex(days)
    cash = starting_balance
    held: dict[str, float] = {}
    out = np.empty(len(days))
    i = 0
    for n, day in enumerate(days):
        day_end = day + pd.Timedelta(days=1)
        while i < len(fills) and fills[i].time < day_end:
            f = fills[i]
            cost = f.amount * f.price
            if f.side == "buy":
                cash -= cost * (1 + f.fee_rate)
                held[f.pair] = held.get(f.pair, 0.0) + f.amount
            else:
                cash += cost * (1 - f.fee_rate)
                held[f.pair] = held.get(f.pair, 0.0) - f.amount
            i += 1
        value = 0.0
        for pair, amt in held.items():
            if abs(amt) > 1e-12:
                px = marks.at[day, pair]
                if math.isnan(px):
                    raise ValueError(f"no close to mark {pair} on {day.date()}")
                value += amt * px
        out[n] = cash + value
    return pd.Series(out, index=days, name="equity")


def sharpe(returns: pd.Series) -> float:
    """Annualised Sharpe of daily simple returns, risk-free rate 0."""
    r = returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(DAYS_PER_YEAR))


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough fall as a positive fraction of the peak."""
    peak = equity.cummax()
    return float(((peak - equity) / peak).max()) if len(equity) else 0.0


@dataclass(frozen=True, slots=True)
class Metrics:
    n_trades: int
    n_force_exit: int
    force_exit_profit: float
    net_profit: float
    final_equity: float
    sharpe_daily: float
    max_drawdown: float
    cagr: float
    exposure: float
    win_rate: float
    avg_hold_days: float
    fees: float
    gross_winning_pnl: float
    fee_ratio: float
    avg_gross_profit_pct: float
    avg_net_profit_pct: float
    top_trade_share_of_net: float | None
    top_trade_share_of_gross_wins: float | None
    scale_downs: int

    def as_dict(self) -> dict:
        return asdict(self)


def compute_metrics(
    trades: list[Mapping],
    closes: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    starting_balance: float,
) -> tuple[Metrics, pd.Series]:
    """Gate 1 metrics on the strategy's own exits; force-exit trades are reported, not counted."""
    own = [t for t in trades if t["exit_reason"] != FORCE_EXIT]
    forced = [t for t in trades if t["exit_reason"] == FORCE_EXIT]
    equity = daily_equity(fills_from_trades(own), closes, start, end, starting_balance)
    rets = equity.pct_change().dropna()
    summ = summarise_trades(own)

    gross = [s.profit_abs + s.fees_abs for s in summ]
    gross_wins = sum(g for g in gross if g > 0)
    fees = sum(s.fees_abs for s in summ)
    net = sum(s.profit_abs for s in summ)
    best = max((s.profit_abs for s in summ), default=0.0)
    years = max((end - start).days, 1) / DAYS_PER_YEAR
    final = float(equity.iloc[-1])

    held_days = pd.Series(False, index=equity.index)
    for s in summ:
        held_days[(held_days.index >= s.open_date.floor("D")) & (held_days.index <= s.close_date.floor("D"))] = True

    metrics = Metrics(
        n_trades=len(summ),
        n_force_exit=len(forced),
        force_exit_profit=float(sum(float(t["profit_abs"]) for t in forced)),
        net_profit=net,
        final_equity=final,
        sharpe_daily=sharpe(rets),
        max_drawdown=max_drawdown(equity),
        cagr=(final / starting_balance) ** (1 / years) - 1 if final > 0 else -1.0,
        exposure=float(held_days.mean()) if len(held_days) else 0.0,
        win_rate=sum(1 for s in summ if s.profit_abs > 0) / len(summ) if summ else 0.0,
        avg_hold_days=float(np.mean([(s.close_date - s.open_date).total_seconds() / 86400 for s in summ]))
        if summ
        else 0.0,
        fees=fees,
        gross_winning_pnl=gross_wins,
        fee_ratio=fees / gross_wins if gross_wins > 0 else math.inf,
        avg_gross_profit_pct=float(np.mean([g / s.stake for g, s in zip(gross, summ, strict=True)])) if summ else 0.0,
        avg_net_profit_pct=float(np.mean([s.profit_abs / s.stake for s in summ])) if summ else 0.0,
        top_trade_share_of_net=best / net if net > 0 else None,
        top_trade_share_of_gross_wins=best / gross_wins if gross_wins > 0 else None,
        scale_downs=sum(s.scale_downs for s in summ),
    )
    return metrics, rets


def buy_and_hold(closes: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Benchmark: fully invested in one asset, no fees."""
    s = closes.loc[start.floor("D") : end.floor("D")].ffill().dropna()
    return {
        "sharpe_daily": sharpe(s.pct_change()),
        "max_drawdown": max_drawdown(s),
        "total_return": float(s.iloc[-1] / s.iloc[0] - 1),
    }
