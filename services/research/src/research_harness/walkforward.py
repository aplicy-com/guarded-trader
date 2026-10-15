"""Walk-forward window geometry and pooled out-of-sample scoring. Pure; no I/O.

Protocol (frozen before any candidate ran; changing it is a new registry trial):
- OOS windows of ``oos_months`` stepping by ``oos_months`` (non-overlapping), the first one
  starting ``is_months`` after the canonical start, the last one ending on or before the
  canonical end.
- Rolling: IS is the ``is_months`` immediately before each OOS window.
- Anchored: IS runs from the canonical start to each OOS window's start.
- Each window is its own backtest that starts flat (indicator warm-up comes from data before
  the window, never from inside it).
- Headline OOS Sharpe is computed on the *pooled* (concatenated) OOS daily returns, not as the
  average of per-window ratios (04-validation-upgrades.md section 6). Headline IS Sharpe is the
  mean of the per-window IS Sharpes.

The candidates in this phase have fixed, pre-registered parameters and no fitting step, so here
walk-forward measures stability across time, not fit decay.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from research_harness.metrics import sharpe

IS_MONTHS = 12
OOS_MONTHS = 3
MIN_OOS_WINDOWS = 8


@dataclass(frozen=True, slots=True)
class Window:
    scheme: str  # "anchored" | "rolling"
    index: int
    is_start: pd.Timestamp
    is_end: pd.Timestamp  # exclusive
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp  # exclusive


def windows(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scheme: str,
    is_months: int = IS_MONTHS,
    oos_months: int = OOS_MONTHS,
) -> list[Window]:
    if scheme not in ("anchored", "rolling"):
        raise ValueError(scheme)
    out = []
    oos_start = start + pd.DateOffset(months=is_months)
    while (oos_end := oos_start + pd.DateOffset(months=oos_months)) <= end:
        is_start = start if scheme == "anchored" else oos_start - pd.DateOffset(months=is_months)
        out.append(Window(scheme, len(out), is_start, oos_start, oos_start, oos_end))
        oos_start = oos_end
    return out


@dataclass(frozen=True, slots=True)
class WalkForwardSummary:
    scheme: str
    n_windows: int
    is_sharpe_mean: float
    oos_sharpe_pooled: float
    oos_over_is: float | None
    oos_trades_per_window: list[int]
    per_window: list[dict]


def summarise(
    scheme: str,
    per_window: list[dict],
    oos_returns: list[pd.Series],
) -> WalkForwardSummary:
    """``per_window`` rows carry ``is_sharpe``, ``oos_sharpe`` and ``oos_trades``."""
    pooled = pd.concat(oos_returns).sort_index() if oos_returns else pd.Series(dtype=float)
    is_mean = float(pd.Series([w["is_sharpe"] for w in per_window]).mean()) if per_window else 0.0
    oos = sharpe(pooled)
    return WalkForwardSummary(
        scheme=scheme,
        n_windows=len(per_window),
        is_sharpe_mean=is_mean,
        oos_sharpe_pooled=oos,
        oos_over_is=oos / is_mean if is_mean > 0 else None,
        oos_trades_per_window=[int(w["oos_trades"]) for w in per_window],
        per_window=per_window,
    )
