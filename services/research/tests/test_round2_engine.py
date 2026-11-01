import math

import numpy as np
import pandas as pd
import pytest

from research_harness import metrics
from research_harness.round2 import engine as eng
from research_harness.round2 import strategies as st

BTC, ETH = st.BTC, st.ETH


def market(close_btc, close_eth=None, open_btc=None, open_eth=None, start="2024-01-01"):
    n = len(close_btc)
    dates = pd.date_range(start, periods=n, freq="D", tz="UTC")
    cb = np.asarray(close_btc, float)
    ob = np.asarray(open_btc, float) if open_btc is not None else np.r_[cb[0], cb[:-1]]
    ce = np.asarray(close_eth if close_eth is not None else np.full(n, 100.0), float)
    oe = np.asarray(open_eth, float) if open_eth is not None else np.r_[ce[0], ce[:-1]]
    return eng.Market(dates, {BTC: ob, ETH: oe}, {BTC: cb, ETH: ce})


def always(_):
    return True


# --- fees, fills, accounting ---------------------------------------------------------------------


def test_fee_is_applied_per_fill_as_freqtrade_spot_model():
    m = market([10, 10, 11, 11], open_btc=[10, 10, 11, 11])
    plan = {0: {BTC: 1.0}, 1: {}}
    res = eng.simulate(m, lambda i, h, w: plan.get(i), always, 0, 4, cost=0.01, balance=100.0)
    buy, sell = res.fills
    assert (buy.day, buy.side, buy.price) == (1, "buy", 10)  # decided at close 0, filled at open 1
    assert buy.notional == pytest.approx(100 / 1.01)
    assert (sell.day, sell.side, sell.price) == (2, "sell", 11)
    assert res.equity[-1] == pytest.approx(100 * 1.1 * 0.99 / 1.01)
    t = res.trades[0]
    assert t["exit_reason"] == eng.EXIT_SIGNAL
    assert t["profit_abs"] == pytest.approx(100 * 1.1 * 0.99 / 1.01 - 100)


def test_decision_fills_at_next_open_not_the_decision_close():
    m = market([10, 20, 20], open_btc=[10, 15, 20])
    res = eng.simulate(m, lambda i, h, w: {BTC: 1.0} if i == 0 else None, always, 0, 3, 0.0, 100.0)
    assert res.fills[0].price == 15  # day 1's open, not day 0's close of 10
    assert res.equity[1] == pytest.approx(100 / 15 * 20)


def test_last_day_decision_is_discarded_and_open_position_is_force_exited_at_close():
    m = market([10, 10, 12], open_btc=[10, 10, 11])
    res = eng.simulate(m, lambda i, h, w: {BTC: 1.0} if i == 0 else ({} if i == 2 else None), always, 0, 3, 0.0, 100.0)
    assert [f.side for f in res.fills] == ["buy", "sell"]
    assert res.fills[-1].force_exit and res.fills[-1].price == 12
    assert res.trades[0]["exit_reason"] == eng.FORCE_EXIT
    assert 2 not in res.decisions


def test_engine_equity_matches_the_harness_rebuild_from_its_own_trade_rows():
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.04, 400)))
    m = market(closes, open_btc=closes * np.exp(rng.normal(0, 0.01, 400)))
    c = st.VolTarget(m, vol_target=0.5, vol_window_days=20, drift_band=0.1)
    c.check = np.asarray(m.dates.dayofweek == 6)  # more rebalances than month-end, to exercise them
    res = eng.simulate(m, st.rule_decide(c), c.is_check_day, 30, 400, 0.009, 25.0)
    assert len(res.fills) > 5
    rebuilt = metrics.daily_equity(
        metrics.fills_from_trades(res.trades), m.closes_frame(), m.dates[30], m.dates[399], 25.0
    )
    assert np.allclose(rebuilt.to_numpy(), res.equity, rtol=1e-12)
    # Gate 1 headline excludes the force exit: an always-in strategy scores zero trades.
    mx, _ = metrics.compute_metrics(res.trades, m.closes_frame(), m.dates[30], m.dates[399], 25.0)
    assert mx.n_trades == 0 and mx.n_force_exit == 1


def test_partial_rebalances_stay_inside_one_trade():
    m = market([10, 10, 20, 20, 20])
    plan = {0: {BTC: 0.5}, 1: {BTC: 0.5}, 2: {BTC: 0.25}}
    res = eng.simulate(m, lambda i, h, w: plan.get(i), always, 0, 5, 0.0, 100.0)
    assert len(res.trades) == 1 and len(res.trades[0]["orders"]) == 3
    assert res.trades[0]["exit_reason"] == eng.FORCE_EXIT


# --- turnover ------------------------------------------------------------------------------------


def test_round_trips_count_notional_turnover_and_skip_force_exits():
    m = market([10] * 8, close_eth=[100] * 8)
    plan = {0: {BTC: 1.0}, 2: {ETH: 1.0}, 4: {ETH: 0.5}}
    res = eng.simulate(m, lambda i, h, w: plan.get(i), always, 0, 8, 0.0, 100.0)
    rt = eng.round_trips_per_year(res.fills, m.dates)
    # entry 0.5 + switch (sell 1, buy 1) 1.0 + half-down 0.25; the final force exit is not counted
    assert rt == {2024: pytest.approx(0.5 + 1.0 + 0.25)}


# --- signals -------------------------------------------------------------------------------------


def test_realised_vol_is_ddof1_log_return_std_times_sqrt365():
    close = np.array([100, 101, 99, 102, 103, 101.5])
    v = st.realised_vol(close, 3)
    lr = np.diff(np.log(close))
    assert math.isnan(v[2])
    assert v[3] == pytest.approx(np.std(lr[0:3], ddof=1) * math.sqrt(365))
    assert v[5] == pytest.approx(np.std(lr[2:5], ddof=1) * math.sqrt(365))


def test_trend_filter_buffer_and_weekly_schedule():
    # 2024-01-07 is a Sunday. SMA(3) of a flat 100 series is 100.
    closes = [100] * 6 + [120] * 7 + [90] * 8
    m = market(closes)
    c = st.TrendFilter(m, sma_days=3, band=0.05)
    assert c.entry(6, BTC)  # 120 > SMA(100,100,120) * 1.05 = 112, on Sunday 2024-01-07
    assert not c.entry(5, BTC)
    assert c.exit(13, BTC)  # 90 < SMA(120,120,90) * 0.95 = 104.5, on Sunday 2024-01-14
    res = eng.simulate(m, st.rule_decide(c), c.is_check_day, 0, len(closes), 0.0, 100.0)
    days = [(m.dates[f.day].date().isoformat(), f.side) for f in res.fills]
    # entry decided Sunday 01-07, filled Monday 01-08; exit decided Sunday 01-14, filled 01-15
    assert days[0] == ("2024-01-08", "buy")
    assert days[1] == ("2024-01-15", "sell")


def test_trend_filter_holds_inside_the_band():
    m = market([100] * 6 + [120] + [103] * 14)
    c = st.TrendFilter(m, sma_days=3, band=0.05)
    res = eng.simulate(m, st.rule_decide(c), c.is_check_day, 0, 21, 0.0, 100.0)
    assert [f.side for f in res.fills if not f.force_exit] == ["buy"]  # 103 stays inside the band around its own SMA


def test_dual_momentum_choice_tie_negative_and_month_end_schedule():
    n = 70
    dates_start = "2024-01-01"
    btc = np.linspace(100, 130, n)
    eth = np.linspace(100, 160, n)
    m = market(btc, eth, start=dates_start)
    c = st.DualMomentum(m, lookback_days=30)
    i = 59  # 2024-02-29, a month end
    assert c.check[i] and not c.check[i - 1]
    assert c.choice(i) == ETH and c.entry(i, ETH) and c.exit(i, BTC)
    tie = st.DualMomentum(market(btc, btc), lookback_days=30)
    assert tie.choice(i) == BTC
    down = st.DualMomentum(market(btc[::-1], eth[::-1]), lookback_days=30)
    assert down.choice(i) is None
    assert st.DualMomentum(m, lookback_days=30).choice(10) is None  # no 30-day history yet


def test_dual_momentum_switch_is_one_sell_then_one_buy_same_open():
    n = 100
    btc = np.r_[np.linspace(100, 200, 40), np.full(60, 200.0)]
    eth = np.r_[np.full(40, 100.0), np.linspace(100, 400, 60)]
    m = market(btc, eth)
    c = st.DualMomentum(m, lookback_days=30)
    res = eng.simulate(m, st.rule_decide(c), c.is_check_day, 0, n, 0.0, 100.0)
    sides = [(f.pair, f.side, f.day) for f in res.fills if not f.force_exit]
    assert sides[0][:2] == (BTC, "buy")
    sell, buy = sides[1], sides[2]
    assert sell[:2] == (BTC, "sell") and buy[:2] == (ETH, "buy") and sell[2] == buy[2]


def test_vol_target_weight_cap_and_drift_band():
    m = market(100 * np.exp(np.cumsum(np.r_[0, np.tile([0.05, -0.05], 50)])))
    c = st.VolTarget(m, vol_target=0.5, vol_window_days=10, drift_band=0.2)
    i = 50
    target = min(1.0, 0.5 / c.vol[i])
    assert c.weight(i, BTC) == pytest.approx(target)
    assert c.rebalance_to(i, BTC, target * 1.19) is None  # inside the 20% band
    assert c.rebalance_to(i, BTC, target * 1.21) == pytest.approx(target)
    calm = st.VolTarget(market(np.linspace(100, 101, 100)), 0.5, 10, 0.2)
    assert calm.weight(50, BTC) == 1.0  # capped, no leverage


def test_trend_vol_sizes_with_vol_and_switches_with_trend():
    m = market(np.r_[np.full(30, 100.0), 100 * np.exp(np.cumsum(np.tile([0.08, -0.02], 30)))])
    c = st.TrendVol(m, sma_days=5, band=0.05, vol_target=0.5, vol_window_days=10, drift_band=0.2)
    i = next(i for i in range(len(m.dates)) if c.check[i] and c.entry(i, BTC))
    assert c.weight(i, BTC) == pytest.approx(min(1.0, 0.5 / c.vt.vol[i]))
    assert c.exit(i, BTC) == c.trend.exit(i, BTC)


# --- nulls ---------------------------------------------------------------------------------------


def test_c11_entry_is_seeded_and_never_fires_where_the_exit_fires():
    m = market(np.r_[np.full(60, 100.0), np.linspace(100, 60, 60), np.linspace(60, 140, 60)])
    c = st.TrendFilter(m, sma_days=10, band=0.05)
    e1 = st.c11_entry(c, m, {BTC: 1.0}, seed=5, start=0, end=180)
    e2 = st.c11_entry(c, m, {BTC: 0.3}, seed=5, start=0, end=180)
    checks = np.flatnonzero(c.check)
    assert all(not e1(i, BTC) for i in checks if c.exit(i, BTC))
    assert any(e1(i, BTC) for i in checks)
    same = st.c11_entry(c, m, {BTC: 0.3}, seed=5, start=0, end=180)
    assert [e2(i, BTC) for i in checks] == [same(i, BTC) for i in checks]
    assert not e1(int(checks[0]) + 1, BTC)  # never on a non-check day


def test_c11_rates_are_entries_over_flat_check_days():
    decisions = {7: None, 14: BTC, 21: BTC, 28: None, 35: None}
    trades = [{"pair": BTC}]
    # flat before decisions on days 7, 14 and 35 (after 28's exit): 3 flat check days, 1 entry
    assert st.c11_rates(st.TrendFilter(market([1.0] * 40), 3, 0.05), decisions, trades) == {BTC: 1 / 3}


def test_matched_states_keep_switches_time_in_market_and_start_state():
    states = [None, None, BTC, BTC, BTC, ETH, ETH, None, None, None, ETH, None]
    rng = np.random.default_rng(0)
    for _ in range(200):
        out = st.matched_states(states, (BTC, ETH), rng)
        assert len(out) == len(states)
        assert sum(s is not None for s in out) == sum(s is not None for s in states)
        assert len(st.runs(out)) == len(st.runs(states))
        assert out[0] is None
        for (a, _), (b, _) in zip(st.runs(out), st.runs(out)[1:], strict=False):
            assert a != b
    seen = {tuple(st.matched_states(states, (BTC, ETH), np.random.default_rng(s))) for s in range(30)}
    assert len(seen) > 10


def test_composition_is_positive_and_sums():
    rng = np.random.default_rng(3)
    for total, parts in [(10, 1), (10, 3), (5, 5), (100, 7)]:
        c = st.composition(total, parts, rng)
        assert len(c) == parts and sum(c) == total and min(c) >= 1


def test_matched_vol_schedule_keeps_count_and_target_multiset():
    rng = np.random.default_rng(1)
    sched = st.matched_vol_schedule(list(range(0, 300, 30)), 0, [0.6, 0.8, 0.9], rng)
    assert len(sched) == 3 and all(d > 0 for d in sched)
    assert sorted(sched.values()) == [0.6, 0.8, 0.9]


def test_path_decide_follows_the_path_and_keeps_candidate_sizing():
    m = market([100.0] * 30)
    c = st.TrendFilter(m, 3, 0.05)
    c.check = np.ones(30, bool)
    path = {i: (BTC if 5 <= i < 10 else None) for i in range(30)}
    res = eng.simulate(m, st.path_decide(c, path), c.is_check_day, 0, 30, 0.0, 100.0)
    assert [(f.side, f.day) for f in res.fills] == [("buy", 6), ("sell", 11)]
