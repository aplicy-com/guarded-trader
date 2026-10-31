"""Random-entry null (candidate C11). Pure; no I/O.

The candidate's exits, stop, sizing, fees and slots are kept; only the entry signal is replaced
by seeded Bernoulli draws at the candidate's own per-pair entry rate. Whatever survives against
this null is attributable to the entry rule rather than to market beta or exit timing
(docs/research/evidence-review-2026-10/02-strategy-candidates.md, C11).
"""

from __future__ import annotations

import zlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


def entry_rates(trades: list[Mapping], bars_per_pair: Mapping[str, int], bar: pd.Timedelta) -> dict[str, float]:
    """Per pair: entries / bars spent flat (not inside one of the candidate's own trades)."""
    rates = {}
    for pair, n_bars in bars_per_pair.items():
        mine = [t for t in trades if t["pair"] == pair]
        in_trade = sum((pd.Timestamp(t["close_date"]) - pd.Timestamp(t["open_date"])) / bar for t in mine)
        flat = max(n_bars - in_trade, 1.0)
        rates[pair] = min(len(mine) / flat, 1.0)
    return rates


def _splitmix64(x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        x = x + np.uint64(0x9E3779B97F4A7C15)
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> np.uint64(31))


def uniforms(pair: str, dates: pd.Series, seed: int) -> np.ndarray:
    """U(0,1) per candle, a pure function of (seed, pair, candle date).

    Counter-based (splitmix64 of the key), so the draw for a given candle is identical whatever
    window or startup period happens to be loaded around it.
    """
    stamps = (pd.to_datetime(dates, utc=True).astype("int64") // 1_000_000_000).to_numpy().astype(np.uint64)
    with np.errstate(over="ignore"):
        key = np.uint64(seed) * np.uint64(0x100000001B3) ^ np.uint64(zlib.crc32(pair.encode()))
        h = _splitmix64(_splitmix64(stamps ^ _splitmix64(np.array([key], dtype=np.uint64))[0]))
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def entry_mask(pair: str, dates: pd.Series, rate: float, seed: int) -> np.ndarray:
    return uniforms(pair, dates, seed) < rate


@dataclass(frozen=True, slots=True)
class NullVerdict:
    seeds: int
    candidate_sharpe: float
    null_sharpe_p95: float
    null_sharpe_median: float
    candidate_mdd: float
    null_mdd_median: float
    candidate_top_share: float | None
    null_top_share_median: float | None
    candidate_trades: int
    null_trades_median: float
    beats_sharpe_p95: bool
    beats_mdd_median: bool
    top_share_not_worse: bool
    passes: bool
    candidate_sharpe_percentile: float

    def as_dict(self) -> dict:
        return asdict(self)


def verdict(candidate: Mapping, nulls: list[Mapping]) -> NullVerdict:
    """C11 gate: Sharpe > null p95 AND MDD < null median AND top-trade share <= null median.

    Rows carry ``sharpe_daily``, ``max_drawdown``, ``top_trade_share_of_gross_wins``, ``n_trades``.
    Top-trade share uses gross winning P&L as the denominator because net profit can be near
    zero or negative for null seeds, which makes a net-based share meaningless.
    """
    sh = np.array([n["sharpe_daily"] for n in nulls])
    mdd = np.array([n["max_drawdown"] for n in nulls])
    shares = [n["top_trade_share_of_gross_wins"] for n in nulls if n["top_trade_share_of_gross_wins"] is not None]
    share_med = float(np.median(shares)) if shares else None
    c_share = candidate["top_trade_share_of_gross_wins"]
    beats_sh = bool(candidate["sharpe_daily"] > np.percentile(sh, 95))
    beats_mdd = bool(candidate["max_drawdown"] < np.median(mdd))
    share_ok = c_share is not None and share_med is not None and c_share <= share_med
    return NullVerdict(
        seeds=len(nulls),
        candidate_sharpe=float(candidate["sharpe_daily"]),
        null_sharpe_p95=float(np.percentile(sh, 95)),
        null_sharpe_median=float(np.median(sh)),
        candidate_mdd=float(candidate["max_drawdown"]),
        null_mdd_median=float(np.median(mdd)),
        candidate_top_share=c_share,
        null_top_share_median=share_med,
        candidate_trades=int(candidate["n_trades"]),
        null_trades_median=float(np.median([n["n_trades"] for n in nulls])),
        beats_sharpe_p95=beats_sh,
        beats_mdd_median=beats_mdd,
        top_share_not_worse=share_ok,
        passes=beats_sh and beats_mdd and share_ok,
        candidate_sharpe_percentile=float((sh < candidate["sharpe_daily"]).mean() * 100),
    )
