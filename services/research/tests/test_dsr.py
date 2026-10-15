import math

import numpy as np
import pytest

from research_harness import dsr


def test_expected_max_sharpe_matches_review_worked_numbers():
    # 04-validation-upgrades.md section 2: sigma 0.03/day -> ~1.66 annualised at N=300, ~1.86 at N=1000.
    assert dsr.expected_max_sharpe(300, 0.03) * math.sqrt(365) == pytest.approx(1.66, abs=0.01)
    assert dsr.expected_max_sharpe(1000, 0.03) * math.sqrt(365) == pytest.approx(1.86, abs=0.01)
    assert dsr.expected_max_sharpe(1, 0.03) == 0.0


def test_min_track_record_matches_review_worked_number():
    # Annualised Sharpe 1.0 vs SR*=0 at 95%, normal returns: ~992 days.
    sr = 1.0 / math.sqrt(365)
    assert dsr.min_track_record(sr, 0.0, skew=0.0, kurt=3.0) == pytest.approx(992, abs=3)
    assert dsr.min_track_record(sr, sr, 0.0, 3.0) == math.inf


def test_psr_is_half_at_the_benchmark_and_monotone():
    assert dsr.psr(0.05, 0.05, 1000, 0.0, 3.0) == pytest.approx(0.5)
    assert dsr.psr(0.08, 0.05, 1000, 0.0, 3.0) > dsr.psr(0.06, 0.05, 1000, 0.0, 3.0)


def test_fat_tails_widen_the_error_and_lower_psr():
    assert dsr.psr(0.06, 0.0, 500, 0.0, 10.0) < dsr.psr(0.06, 0.0, 500, 0.0, 3.0)


def test_deflated_sharpe_more_trials_means_lower_dsr():
    r = np.random.default_rng(0).normal(0.002, 0.03, 1500)
    few = dsr.deflated_sharpe(r, n_trials=3, sigma_trials=0.03)
    many = dsr.deflated_sharpe(r, n_trials=300, sigma_trials=0.03)
    assert many.dsr < few.dsr
    assert few.psr_vs_zero > few.dsr


def test_deflated_sharpe_undefined_without_dispersion():
    r = np.random.default_rng(1).normal(0, 0.02, 200)
    out = dsr.deflated_sharpe(r, n_trials=1, sigma_trials=None)
    assert out.dsr is None
    assert out.expected_max_sr_period is None
