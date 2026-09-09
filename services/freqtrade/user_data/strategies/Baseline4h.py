"""Baseline4h — work package 2C (`docs/phase-2-plan.md`).

Purpose: validate the execution path (data -> signal -> order -> ledger),
not to be a strategy worth promoting. See
`docs/research/03-baseline-backtest.md` for the honest backtest result and
its assessment against Gate 1 (`docs/08-paper-exit-criteria.md`).

Logic — simple long-only trend-following, single timeframe (4h):

- Entry: `ema_fast` crosses above `ema_slow` (classic moving-average
  trend-start signal) while trading volume on the candle is non-zero
  (guards against stale/gappy candles producing a false cross).
- Exit (signal): `ema_fast` crosses back below `ema_slow` — the same
  indicator that generated the entry is used to recognise the trend has
  ended, so entry and exit share one model rather than two independent
  ones.
- Exit (risk): a fixed, non-trailing ATR stop. On entry, the stop price is
  set once to `entry_price - atr_multiplier * ATR(atr_period)`, using the
  ATR value from the candle the trade opened on. It does not trail as
  price moves — this is a stop-loss, not a profit-lock mechanism, keeping
  the strategy's only two behaviours (ride the trend / cut the loss)
  independent and easy to reason about. Implemented via
  `custom_stoploss` + `stoploss_from_absolute`, because Freqtrade's static
  `stoploss` attribute cannot vary by trade. The class `stoploss` below is
  the required fallback only (effectively disabled — the ATR stop is
  always tighter) and is never expected to fire itself.
- `minimal_roi` is effectively disabled (`{"0": 10.0}`, i.e. would require
  a 1000% gain) so the EMA-cross exit and the ATR stop are the only two
  ways a position closes — no third, undocumented exit path.

Tunable parameters (4, within the NFR5 <=6 cap, `docs/02-requirements.md`):

| Parameter          | Value | Role                                   |
|---------------------|-------|-----------------------------------------|
| `ema_fast_period`   | 20    | Fast trend EMA                          |
| `ema_slow_period`   | 50    | Slow trend EMA                          |
| `atr_period`        | 14    | ATR lookback for the stop distance      |
| `atr_multiplier`    | 2.0   | Stop distance = this many ATRs from entry|

These are textbook defaults (20/50 EMA cross, 14-period ATR, 2x ATR stop),
not fit to this backtest — see `CLAUDE.md` "Do not tune parameters to
improve results" and the instruction behind
`docs/research/03-baseline-backtest.md`.
"""

from pandas import DataFrame
from technical import qtpylib

import talib.abstract as ta
from freqtrade.strategy import IStrategy, stoploss_from_absolute


class Baseline4h(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"

    # Tunable parameters (4) — see module docstring. Fixed, not hyperopted.
    ema_fast_period = 20
    ema_slow_period = 50
    atr_period = 14
    atr_multiplier = 2.0

    # Required static fallback only; the real stop is custom_stoploss below,
    # which is always tighter. Never expected to fire on its own.
    minimal_roi = {"0": 10.0}
    stoploss = -0.99
    use_custom_stoploss = True

    can_short = False
    process_only_new_candles = True
    startup_candle_count = max(ema_slow_period, atr_period) + 10

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
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast_period)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow_period)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"])
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1
        return dataframe

    def custom_stoploss(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        """Fixed (non-trailing) ATR stop, set once from the entry candle."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
        candles_at_or_before_entry = dataframe.loc[dataframe["date"] <= trade.open_date_utc]
        if candles_at_or_before_entry.empty:
            # No analyzed candle at/before entry yet (should not happen in
            # backtest/dry-run once warmed up) — fall back to the wide
            # static stoploss rather than guessing a stop distance.
            return self.stoploss

        entry_atr = candles_at_or_before_entry.iloc[-1]["atr"]
        stop_price = trade.open_rate - (entry_atr * self.atr_multiplier)
        return stoploss_from_absolute(
            stop_price,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )
