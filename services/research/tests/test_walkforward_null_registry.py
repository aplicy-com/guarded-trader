import sqlite3

import numpy as np
import pandas as pd
import pytest

from research_harness import null, walkforward
from research_harness.registry import DuplicateTrialError, Registry

START = pd.Timestamp("2022-01-01", tz="UTC")
END = pd.Timestamp("2026-10-01", tz="UTC")


def test_canonical_windows_are_fifteen_non_overlapping_quarters():
    for scheme in ("anchored", "rolling"):
        ws = walkforward.windows(START, END, scheme)
        assert len(ws) == 15 >= walkforward.MIN_OOS_WINDOWS
        assert ws[0].oos_start == pd.Timestamp("2023-01-01", tz="UTC")
        assert ws[-1].oos_end == END
        for a, b in zip(ws, ws[1:], strict=False):
            assert a.oos_end == b.oos_start
        for w in ws:
            assert w.is_end == w.oos_start  # IS never overlaps OOS
    anchored = walkforward.windows(START, END, "anchored")
    rolling = walkforward.windows(START, END, "rolling")
    assert all(w.is_start == START for w in anchored)
    assert all(w.is_start == w.oos_start - pd.DateOffset(months=12) for w in rolling)


def test_pooled_oos_sharpe_is_on_concatenated_returns_not_averaged_ratios():
    r1 = pd.Series([0.01, 0.02], index=pd.date_range("2023-01-01", periods=2, tz="UTC"))
    r2 = pd.Series([-0.01, 0.03], index=pd.date_range("2023-04-01", periods=2, tz="UTC"))
    rows = [
        {"is_sharpe": 2.0, "oos_sharpe": 1.0, "oos_trades": 3},
        {"is_sharpe": 1.0, "oos_sharpe": 0.5, "oos_trades": 4},
    ]
    s = walkforward.summarise("rolling", rows, [r1, r2])
    pooled = pd.concat([r1, r2])
    assert s.oos_sharpe_pooled == pytest.approx(pooled.mean() / pooled.std(ddof=1) * np.sqrt(365))
    assert s.is_sharpe_mean == 1.5
    assert s.oos_trades_per_window == [3, 4]


def test_null_uniforms_are_deterministic_and_window_independent():
    dates = pd.Series(pd.date_range("2022-01-01", periods=400, freq="D", tz="UTC"))
    a = null.uniforms("BTC/USD", dates, seed=7)
    b = null.uniforms("BTC/USD", dates.iloc[100:].reset_index(drop=True), seed=7)
    assert np.array_equal(a[100:], b)
    assert not np.array_equal(a, null.uniforms("BTC/USD", dates, seed=8))
    assert not np.array_equal(a, null.uniforms("ETH/USD", dates, seed=7))
    assert a.min() >= 0 and a.max() < 1
    big = null.uniforms("BTC/USD", pd.Series(pd.date_range("2000-01-01", periods=20000, freq="4h", tz="UTC")), 3)
    assert abs(big.mean() - 0.5) < 0.01
    assert abs((big < 0.1).mean() - 0.1) < 0.01


@pytest.mark.parametrize("unit", ["s", "ms", "us"])
def test_null_uniforms_do_not_depend_on_datetime_resolution(unit):
    ns = pd.Series(pd.date_range("2022-01-01", periods=300, freq="D", tz="UTC"))
    coarse = ns.astype(f"datetime64[{unit}, UTC]")
    a, b = null.uniforms("BTC/USD", ns, 4), null.uniforms("BTC/USD", coarse, 4)
    assert np.array_equal(a, b)
    assert len(set(b.tolist())) == 300  # one independent draw per candle


def test_entry_rates_use_flat_bars():
    bar = pd.Timedelta("1D")
    trades = [{"pair": "BTC/USD", "open_date": "2024-01-01", "close_date": "2024-01-11"}]
    assert null.entry_rates(trades, {"BTC/USD": 110, "ETH/USD": 50}, bar) == {"BTC/USD": 0.01, "ETH/USD": 0.0}


def row(sharpe, mdd, share, n=10):
    return {"sharpe_daily": sharpe, "max_drawdown": mdd, "top_trade_share_of_gross_wins": share, "n_trades": n}


def test_null_verdict_needs_all_three_conditions():
    nulls = [row(s, 0.5, 0.3) for s in np.linspace(-1, 1, 101)]
    assert null.verdict(row(1.5, 0.3, 0.2), nulls).passes
    assert not null.verdict(row(0.5, 0.3, 0.2), nulls).passes  # Sharpe below p95
    assert not null.verdict(row(1.5, 0.6, 0.2), nulls).passes  # worse drawdown than null median
    assert not null.verdict(row(1.5, 0.3, 0.4), nulls).passes  # more concentrated than null median


def test_registry_is_append_only_and_refuses_rescoring(tmp_path):
    reg = Registry(tmp_path / "r.sqlite")
    kw = dict(
        strategy="X",
        family="f",
        hypothesis="h",
        params={"a": 1},
        canonical_timerange="20220101-20261001",
        fee=0.009,
        data_snapshot_id="snap",
        freqtrade_version="2026.8",
        source=b"code",
    )
    tid = reg.preregister(**kw)
    assert reg.n_trials() == 1
    assert reg.preregister(**kw) == tid  # registered but unscored: resume, do not add
    reg.record_result(tid, sharpe_daily=0.5, sharpe_period=0.026, n_trades=10, metrics={}, daily_returns=[0.0])
    with pytest.raises(DuplicateTrialError):
        reg.preregister(**kw)
    assert reg.preregister(**{**kw, "params": {"a": 2}}) != tid  # any change is a new trial
    assert reg.n_trials() == 2
    for sql in ("UPDATE trials SET hypothesis='x'", "DELETE FROM trials", "DELETE FROM results"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            reg._db.execute(sql)


def test_registry_requires_a_hypothesis(tmp_path):
    reg = Registry(tmp_path / "r.sqlite")
    with pytest.raises(sqlite3.IntegrityError):
        reg.preregister(
            strategy="X",
            family="f",
            hypothesis="  ",
            params={},
            canonical_timerange="t",
            fee=0.009,
            data_snapshot_id="s",
            freqtrade_version="v",
            source=b"",
        )


def test_sigma_trials_needs_two_scored():
    reg = Registry(":memory:")
    assert reg.sigma_trials() is None


def test_readonly_registry_reads_recorded_results_and_cannot_write(tmp_path):
    path = tmp_path / "r.sqlite"
    reg = Registry(path)
    args = dict(
        strategy="S",
        family="f",
        hypothesis="h",
        params={"a": 1},
        canonical_timerange="x",
        fee=0.009,
        data_snapshot_id="d",
        freqtrade_version="v",
        source=b"src",
    )
    tid = reg.preregister(**args)
    reg.record_result(tid, sharpe_daily=0.5, sharpe_period=0.03, n_trades=7, metrics={}, daily_returns=[0.1, -0.2])
    reg.close()
    ro = Registry.open_readonly(path)
    from research_harness.registry import strategy_hash

    rec = ro.recorded(strategy_hash(b"src", {"a": 1}, 0.009, "d", "v"))
    assert rec["trial_id"] == tid and rec["sharpe_daily"] == 0.5 and rec["n_trades"] == 7
    assert ro.recorded("nope") is None
    with pytest.raises(sqlite3.OperationalError):
        ro.preregister(**{**args, "source": b"other"})
    assert ro.n_trials() == 1
