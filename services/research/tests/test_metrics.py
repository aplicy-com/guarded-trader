import math

import numpy as np
import pandas as pd
import pytest

from research_harness import metrics

D = pd.Timestamp("2024-01-01", tz="UTC")


def ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def trade(pair, open_ts, close_ts, amount, open_px, close_px, fee=0.01, reason="exit_signal"):
    stake = amount * open_px
    profit = amount * close_px * (1 - fee) - stake * (1 + fee)
    return {
        "pair": pair,
        "open_date": open_ts,
        "close_date": close_ts,
        "stake_amount": stake,
        "profit_abs": profit,
        "fee_open": fee,
        "fee_close": fee,
        "exit_reason": reason,
        "orders": [
            {
                "amount": amount,
                "safe_price": open_px,
                "ft_order_side": "buy",
                "ft_is_entry": True,
                "order_filled_timestamp": ms(open_ts),
                "cost": stake,
            },
            {
                "amount": amount,
                "safe_price": close_px,
                "ft_order_side": "sell",
                "ft_is_entry": False,
                "order_filled_timestamp": ms(close_ts),
                "cost": amount * close_px,
            },
        ],
    }


def closes(values):
    idx = pd.date_range(D, periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"BTC/USD": values}, index=idx)


def test_equity_marks_open_position_to_daily_close_and_charges_fees_both_sides():
    t = trade("BTC/USD", D + pd.Timedelta(days=1), D + pd.Timedelta(days=3), 1.0, 10.0, 12.0)
    eq = metrics.daily_equity(
        metrics.fills_from_trades([t]), closes([10, 10, 11, 12, 12]), D, D + pd.Timedelta(days=4), 100
    )
    # day1: cash 100 - 10.1 = 89.9, +1 BTC @10 -> 99.9; day2 @11 -> 100.9; day3 sold 12*0.99=11.88 -> 101.78
    assert list(np.round(eq.to_numpy(), 6)) == [100, 99.9, 100.9, 101.78, 101.78]
    assert eq.iloc[-1] == pytest.approx(100 + t["profit_abs"])


def test_equity_handles_partial_scale_down():
    open_ts, cut_ts, close_ts = D, D + pd.Timedelta(days=1), D + pd.Timedelta(days=2)
    t = {
        "pair": "BTC/USD",
        "fee_open": 0.0,
        "fee_close": 0.0,
        "orders": [
            {
                "amount": 2.0,
                "safe_price": 10.0,
                "ft_order_side": "buy",
                "ft_is_entry": True,
                "order_filled_timestamp": ms(open_ts),
            },
            {
                "amount": 1.0,
                "safe_price": 11.0,
                "ft_order_side": "sell",
                "ft_is_entry": False,
                "order_filled_timestamp": ms(cut_ts),
            },
            {
                "amount": 1.0,
                "safe_price": 12.0,
                "ft_order_side": "sell",
                "ft_is_entry": False,
                "order_filled_timestamp": ms(close_ts),
            },
        ],
    }
    eq = metrics.daily_equity(metrics.fills_from_trades([t]), closes([10, 11, 12]), D, close_ts, 100)
    assert list(eq.to_numpy()) == [100, 102, 103]


def test_equity_refuses_to_mark_without_a_price():
    t = trade("BTC/USD", D, D + pd.Timedelta(days=2), 1.0, 10.0, 10.0)
    c = closes([np.nan, np.nan, 10])
    with pytest.raises(ValueError, match="no close"):
        metrics.daily_equity(metrics.fills_from_trades([t]), c, D, D + pd.Timedelta(days=2), 100)


def test_sharpe_and_drawdown():
    r = pd.Series([0.01, -0.01, 0.02, 0.0])
    assert metrics.sharpe(r) == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(365))
    assert metrics.sharpe(pd.Series([0.01, 0.01])) == 0.0
    assert metrics.max_drawdown(pd.Series([100, 120, 90, 130, 65])) == pytest.approx(0.5)


def test_force_exits_are_excluded_from_headline_and_reported():
    own = trade("BTC/USD", D, D + pd.Timedelta(days=1), 1.0, 10.0, 11.0)
    forced = trade("BTC/USD", D + pd.Timedelta(days=2), D + pd.Timedelta(days=3), 1.0, 10.0, 20.0, reason="force_exit")
    m, _ = metrics.compute_metrics([own, forced], closes([10, 11, 10, 20]), D, D + pd.Timedelta(days=3), 100)
    assert m.n_trades == 1
    assert m.n_force_exit == 1
    assert m.force_exit_profit == pytest.approx(forced["profit_abs"])
    assert m.net_profit == pytest.approx(own["profit_abs"])
    assert m.final_equity == pytest.approx(100 + own["profit_abs"])


def test_fee_ratio_and_top_trade_share():
    a = trade("BTC/USD", D, D + pd.Timedelta(days=1), 1.0, 10.0, 12.0)
    b = trade("BTC/USD", D + pd.Timedelta(days=1), D + pd.Timedelta(days=2), 1.0, 12.0, 10.0)
    m, _ = metrics.compute_metrics([a, b], closes([10, 12, 10]), D, D + pd.Timedelta(days=2), 100)
    fees = 0.01 * (10 + 12) + 0.01 * (12 + 10)
    assert m.fees == pytest.approx(fees)
    assert m.gross_winning_pnl == pytest.approx(2.0)  # only trade a wins before fees
    assert m.fee_ratio == pytest.approx(fees / 2.0)
    assert m.net_profit < 0
    assert m.top_trade_share_of_net is None  # undefined when net <= 0
    assert m.top_trade_share_of_gross_wins == pytest.approx(a["profit_abs"] / 2.0)


def test_daily_closes_takes_last_intraday_close():
    df = pd.DataFrame({"date": pd.date_range(D, periods=12, freq="4h", tz="UTC"), "close": np.arange(12.0)})
    out = metrics.daily_closes({"BTC/USD": df})
    assert list(out["BTC/USD"]) == [5.0, 11.0]
