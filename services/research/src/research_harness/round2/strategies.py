"""The four round-2 candidates (frozen in candidates-round2.json) and their two nulls. Pure.

Each candidate is split into the parts the C11 null needs to keep or replace: ``entry``,
``exit``, ``weight`` (sizing on entry) and ``rebalance_to`` (drift rule while held). All
indicators use candles up to and including the decision day only.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from research_harness import null as c11
from research_harness.round2.engine import Decide, Market

BTC, ETH = "BTC/USD", "ETH/USD"
DAYS_PER_YEAR = 365


def sma(close: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(close).rolling(n, min_periods=n).mean().to_numpy()


def realised_vol(close: np.ndarray, n: int) -> np.ndarray:
    lr = np.log(pd.Series(close)).diff()
    return (lr.rolling(n, min_periods=n).std(ddof=1) * math.sqrt(DAYS_PER_YEAR)).to_numpy()


def trailing_return(close: np.ndarray, days: int) -> np.ndarray:
    s = pd.Series(close)
    return (s / s.shift(days) - 1).to_numpy()


def weekly(dates: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(dates.dayofweek == 6)  # Sunday: last daily candle of the ISO week


def month_end(dates: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray((dates + pd.Timedelta(days=1)).day == 1)


@dataclass
class Candidate:
    cid: str
    pairs: tuple[str, ...]
    check: np.ndarray  # bool per grid day
    always_in: bool = False

    def entry(self, i: int, pair: str) -> bool:
        raise NotImplementedError

    def exit(self, i: int, pair: str) -> bool:
        raise NotImplementedError

    def weight(self, i: int, pair: str) -> float:
        return 1.0

    def rebalance_to(self, i: int, pair: str, w_now: float) -> float | None:
        return None

    def is_check_day(self, i: int) -> bool:
        return bool(self.check[i])


class TrendFilter(Candidate):
    """R2-01: BTC while close > SMA * (1 + band) until close < SMA * (1 - band)."""

    def __init__(self, m: Market, sma_days: int, band: float) -> None:
        super().__init__("R2-01", (BTC,), weekly(m.dates))
        self.close = m.close[BTC]
        self.sma = sma(self.close, sma_days)
        self.band = band

    def entry(self, i: int, pair: str) -> bool:
        return bool(self.close[i] > self.sma[i] * (1 + self.band))  # NaN SMA -> False

    def exit(self, i: int, pair: str) -> bool:
        return bool(self.close[i] < self.sma[i] * (1 - self.band))


class DualMomentum(Candidate):
    """R2-02: the BTC/ETH pair with the higher 12-month return if > 0 (tie: BTC), else cash."""

    def __init__(self, m: Market, lookback_days: int) -> None:
        super().__init__("R2-02", (BTC, ETH), month_end(m.dates))
        self.ret = {p: trailing_return(m.close[p], lookback_days) for p in (BTC, ETH)}

    def choice(self, i: int) -> str | None:
        rb, re = self.ret[BTC][i], self.ret[ETH][i]
        if math.isnan(rb) or math.isnan(re):
            return None
        best, r = (BTC, rb) if rb >= re else (ETH, re)
        return best if r > 0 else None

    def entry(self, i: int, pair: str) -> bool:
        return self.choice(i) == pair

    def exit(self, i: int, pair: str) -> bool:
        return self.choice(i) != pair


class VolTarget(Candidate):
    """R2-03: BTC at min(1, vol_target / realised vol), rebalanced on > drift_band relative drift."""

    def __init__(self, m: Market, vol_target: float, vol_window_days: int, drift_band: float) -> None:
        super().__init__("R2-03", (BTC,), month_end(m.dates), always_in=True)
        self.vol = realised_vol(m.close[BTC], vol_window_days)
        self.vol_target, self.drift_band = vol_target, drift_band

    def weight(self, i: int, pair: str) -> float:
        return min(1.0, self.vol_target / self.vol[i])

    def entry(self, i: int, pair: str) -> bool:
        return bool(self.vol[i] > 0)  # NaN (warm-up) -> False

    def exit(self, i: int, pair: str) -> bool:
        return False

    def rebalance_to(self, i: int, pair: str, w_now: float) -> float | None:
        if not self.vol[i] > 0:
            return None
        target = self.weight(i, pair)
        return target if abs(w_now - target) / target > self.drift_band else None


class TrendVol(Candidate):
    """R2-04: R2-01's on/off state, R2-03's sizing and drift rule, checked weekly."""

    def __init__(
        self, m: Market, sma_days: int, band: float, vol_target: float, vol_window_days: int, drift_band: float
    ) -> None:
        super().__init__("R2-04", (BTC,), weekly(m.dates))
        self.trend = TrendFilter(m, sma_days, band)
        self.vt = VolTarget(m, vol_target, vol_window_days, drift_band)

    def entry(self, i: int, pair: str) -> bool:
        return self.trend.entry(i, pair) and self.vt.entry(i, pair)

    def exit(self, i: int, pair: str) -> bool:
        return self.trend.exit(i, pair)

    def weight(self, i: int, pair: str) -> float:
        return self.vt.weight(i, pair)

    def rebalance_to(self, i: int, pair: str, w_now: float) -> float | None:
        return self.vt.rebalance_to(i, pair, w_now)


def build(cid: str, m: Market, params: Mapping[str, float]) -> Candidate:
    p = dict(params)
    if cid == "R2-01":
        return TrendFilter(m, int(p["sma_days"]), float(p["band"]))
    if cid == "R2-02":
        return DualMomentum(m, int(p["lookback_days"]))
    if cid == "R2-03":
        return VolTarget(m, float(p["vol_target"]), int(p["vol_window_days"]), float(p["drift_band"]))
    if cid == "R2-04":
        return TrendVol(
            m,
            int(p["sma_days"]),
            float(p["band"]),
            float(p["vol_target"]),
            int(p["vol_window_days"]),
            float(p["drift_band"]),
        )
    raise KeyError(cid)


# --- decision functions --------------------------------------------------------------------------

EntryFn = Callable[[int, str], bool]


def rule_decide(c: Candidate, entry: EntryFn | None = None) -> Decide:
    """The candidate's own decision logic; ``entry`` replaces its entry signal (C11 null)."""
    enter = entry or c.entry

    def decide(i: int, held: str | None, w: float) -> dict[str, float] | None:
        if held is not None and not c.exit(i, held):
            r = c.rebalance_to(i, held, w)
            return {held: r} if r is not None else None
        for p in c.pairs:  # flat, or exiting `held` this check day (whitelist order)
            if p != held and enter(i, p):
                return {p: c.weight(i, p)}
        return {} if held is not None else None

    return decide


def c11_entry(c: Candidate, m: Market, rates: Mapping[str, float], seed: int, start: int, end: int) -> EntryFn:
    """Seeded Bernoulli entries on check days; never where the candidate's own exit fires."""
    days = np.flatnonzero(c.check[start:end]) + start
    dates = pd.Series(m.dates[days])
    draws = {p: dict(zip(days.tolist(), c11.uniforms(p, dates, seed).tolist(), strict=True)) for p in c.pairs}

    def entry(i: int, pair: str) -> bool:
        return draws[pair].get(i, 1.0) < rates.get(pair, 0.0) and not c.exit(i, pair)

    return entry


def c11_rates(c: Candidate, decisions: Mapping[int, str | None], trades: Sequence[Mapping]) -> dict[str, float]:
    """Per pair: the candidate's entries / check days on which it started flat."""
    flat, prev = 0, None
    for i in sorted(decisions):
        if prev is None:
            flat += 1
        prev = decisions[i]
    return {p: min(sum(1 for t in trades if t["pair"] == p) / max(flat, 1), 1.0) for p in c.pairs}


# --- matched switching null ----------------------------------------------------------------------


def runs(states: Sequence[str | None]) -> list[tuple[str | None, int]]:
    out: list[tuple[str | None, int]] = []
    for s in states:
        if out and out[-1][0] == s:
            out[-1] = (s, out[-1][1] + 1)
        else:
            out.append((s, 1))
    return out


def composition(total: int, parts: int, rng: np.random.Generator) -> list[int]:
    """Uniform random composition of ``total`` into ``parts`` positive integers."""
    if parts == 0:
        return []
    cuts = np.sort(rng.choice(np.arange(1, total), size=parts - 1, replace=False)) if parts > 1 else np.array([], int)
    edges = np.concatenate([[0], cuts, [total]])
    return np.diff(edges).astype(int).tolist()


def matched_states(states: Sequence[str | None], pairs: Sequence[str], rng: np.random.Generator) -> list[str | None]:
    """Same run sequence (in/out pattern and count), same check periods in and out, random lengths.

    With two pairs, each in-market run's pair is random; a run directly after another
    in-market run takes the other pair, so the number of switches is kept.
    """
    rs = runs(states)
    in_idx = [k for k, (s, _) in enumerate(rs) if s is not None]
    out_idx = [k for k, (s, _) in enumerate(rs) if s is None]
    lengths = [0] * len(rs)
    for idx in (in_idx, out_idx):
        for k, n in zip(idx, composition(sum(rs[k][1] for k in idx), len(idx), rng), strict=True):
            lengths[k] = n
    labels: list[str | None] = []
    for k, (s, _) in enumerate(rs):
        if s is None:
            labels.append(None)
        elif len(pairs) == 1:
            labels.append(pairs[0])
        elif k > 0 and labels[k - 1] is not None:
            labels.append(next(p for p in pairs if p != labels[k - 1]))
        else:
            labels.append(pairs[int(rng.integers(len(pairs)))])
    return [lab for lab, n in zip(labels, lengths, strict=True) for _ in range(n)]


def path_decide(c: Candidate, path: Mapping[int, str | None]) -> Decide:
    """Follow a prescribed state per check day; while in, the candidate's own sizing and drift rule."""

    def decide(i: int, held: str | None, w: float) -> dict[str, float] | None:
        want = path.get(i, held)
        if want == held:
            if held is None:
                return None
            r = c.rebalance_to(i, held, w)
            return {held: r} if r is not None else None
        return {} if want is None else {want: c.weight(i, want)}

    return decide


def schedule_decide(pair: str, entry_day: int, entry_weight: float, rebalances: Mapping[int, float]) -> Decide:
    """R2-03's matched null: the candidate's entry, then rebalances on given days to given weights."""

    def decide(i: int, held: str | None, w: float) -> dict[str, float] | None:
        if held is None:
            return {pair: entry_weight} if i == entry_day else None
        return {pair: rebalances[i]} if i in rebalances else None

    return decide


def matched_vol_schedule(
    check_days: Sequence[int], entry_day: int, targets: Sequence[float], rng: np.random.Generator
) -> dict[int, float]:
    """Random rebalance days (same count) after the entry, the candidate's targets in random order."""
    pool = [d for d in check_days if d > entry_day]
    n = min(len(targets), len(pool))
    days = sorted(rng.choice(pool, size=n, replace=False).tolist()) if n else []
    order = rng.permutation(len(targets))[:n]
    return {int(d): float(targets[j]) for d, j in zip(days, order, strict=True)}
