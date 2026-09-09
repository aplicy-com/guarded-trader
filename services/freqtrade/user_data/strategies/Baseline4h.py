"""Placeholder strategy for Phase 2 work package 2A.

Compiles and loads under Freqtrade so `make up` / `make backtest` succeed,
but never emits an entry signal. Real trend-following logic (EMA cross +
ATR stop, <=6 tunable params per NFR5) is added in work package 2C — see
docs/phase-2-plan.md.
"""

from pandas import DataFrame

from freqtrade.strategy import IStrategy


class Baseline4h(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"

    minimal_roi = {"0": 10.0}
    stoploss = -0.99

    can_short = False
    process_only_new_candles = True
    startup_candle_count = 0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe
