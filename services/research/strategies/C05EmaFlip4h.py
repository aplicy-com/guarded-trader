"""C05 - Baseline4h with the 2x ATR stop removed (one-variable A/B).

Pre-registered in docs/research/evidence-review-2026-10/02-strategy-candidates.md (C05) and
reported in docs/research/05-first-candidates.md. Identical to
services/freqtrade/user_data/strategies/Baseline4h.py in every respect except the exit-on-risk:
the fixed ATR(14) x 2.0 stop is gone and only a -20% catastrophe stop remains (the hard loss
floor the capital rules require). Same 4h timeframe, same EMA(20/50) cross entry and cross-down
exit, same volume guard, same protections, ROI disabled.

Hypothesis: the stop, not the cross, cost Baseline4h its edge ("a change of trend is the best
stop loss", Clare et al.). If removing it changes nothing, the cross has no edge.

Tunable parameters (3): ema_fast_period, ema_slow_period, catastrophe stop. Not tuned.
"""

from pandas import DataFrame
from technical import qtpylib

import talib.abstract as ta
from freqtrade.strategy import IStrategy


class C05EmaFlip4h(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"

    ema_fast_period = 20
    ema_slow_period = 50

    minimal_roi = {"0": 10.0}
    stoploss = -0.20  # catastrophe stop only (replaces Baseline4h's 2x ATR stop)

    can_short = False
    process_only_new_candles = True
    startup_candle_count = ema_slow_period + 10

    # Unchanged from Baseline4h so the A/B differs in the stop only.
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 2},
        {
            "method": "StoplossGuard",
            "lookback_period_candles": 6,
            "trade_limit": 3,
            "stop_duration_candles": 3,
            "only_per_pair": False,
            "only_per_side": False,
        },
        {
            "method": "MaxDrawdown",
            "lookback_period_candles": 48,
            "trade_limit": 20,
            "stop_duration_candles": 3,
            "max_allowed_drawdown": 0.1,
        },
    ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast_period)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow_period)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"])
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
