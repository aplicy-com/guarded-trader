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

    # First of two independent R4 layers (Freqtrade built-in) — see
    # docs/04-architecture/execution-freqtrade.md. Freqtrade 2026.8
    # deprecated the config-level `protections` key, so these live here
    # instead. Conductor's own check is Phase 3+; these are time-bound
    # locks, not a durable human-re-enable halt, so R4 AC4.2/AC4.6 are not
    # fully satisfied by this alone. TBD (Phase 3).
    protections = [
        {
            "method": "CooldownPeriod",
            "stop_duration_candles": 2,
        },
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
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe
