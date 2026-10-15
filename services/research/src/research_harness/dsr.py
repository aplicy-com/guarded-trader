"""Probabilistic and Deflated Sharpe Ratio, minimum track record length. Pure; no I/O.

Bailey & Lopez de Prado (2014), as sketched in
docs/research/evidence-review-2026-10/04-validation-upgrades.md section 2. Every Sharpe here is
*per period* (daily, not annualised); ``kurt`` is the raw (non-excess) kurtosis, 3 for a normal.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

EULER_GAMMA = 0.5772156649015329


def sharpe_std(sr: float, t: int, skew: float, kurt: float) -> float:
    """Standard error of a per-period Sharpe estimate under non-normal returns."""
    return math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12) / (t - 1))


def psr(sr: float, sr_star: float, t: int, skew: float, kurt: float) -> float:
    """P(true Sharpe > sr_star) given the observed ``sr`` over ``t`` periods."""
    return float(stats.norm.cdf((sr - sr_star) / sharpe_std(sr, t, skew, kurt)))


def expected_max_sharpe(n_trials: int, sigma_trials: float) -> float:
    """Expected best per-period Sharpe among ``n_trials`` zero-skill trials."""
    if n_trials < 2:
        return 0.0
    z1 = stats.norm.ppf(1 - 1 / n_trials)
    z2 = stats.norm.ppf(1 - 1 / (n_trials * math.e))
    return float(sigma_trials * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2))


def min_track_record(sr: float, sr_star: float, skew: float, kurt: float, conf: float = 0.95) -> float:
    """Periods needed for PSR(sr_star) >= conf; infinite if sr <= sr_star."""
    if sr <= sr_star:
        return math.inf
    z = stats.norm.ppf(conf)
    return 1 + (1 - skew * sr + (kurt - 1) / 4 * sr**2) * (z / (sr - sr_star)) ** 2


@dataclass(frozen=True, slots=True)
class DeflatedSharpe:
    sr_period: float
    t: int
    skew: float
    kurt: float
    n_trials: int
    sigma_trials: float | None
    expected_max_sr_period: float | None
    psr_vs_zero: float
    dsr: float | None
    min_trl_vs_zero: float
    min_trl_vs_expected_max: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def deflated_sharpe(returns: np.ndarray, n_trials: int, sigma_trials: float | None) -> DeflatedSharpe:
    """DSR of one return series against the registry's trial count and Sharpe dispersion.

    ``sigma_trials`` is the cross-trial std of per-period Sharpe; ``None`` (fewer than two
    scored trials) leaves DSR undefined rather than guessing.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    t = len(r)
    sd = r.std(ddof=1)
    sr = float(r.mean() / sd) if sd > 0 else 0.0
    skew = float(stats.skew(r)) if sd > 0 else 0.0
    kurt = float(stats.kurtosis(r, fisher=False)) if sd > 0 else 3.0
    sr_star = expected_max_sharpe(n_trials, sigma_trials) if sigma_trials is not None else None
    return DeflatedSharpe(
        sr_period=sr,
        t=t,
        skew=skew,
        kurt=kurt,
        n_trials=n_trials,
        sigma_trials=sigma_trials,
        expected_max_sr_period=sr_star,
        psr_vs_zero=psr(sr, 0.0, t, skew, kurt),
        dsr=psr(sr, sr_star, t, skew, kurt) if sr_star is not None else None,
        min_trl_vs_zero=min_track_record(sr, 0.0, skew, kurt),
        min_trl_vs_expected_max=min_track_record(sr, sr_star, skew, kurt) if sr_star is not None else None,
    )
