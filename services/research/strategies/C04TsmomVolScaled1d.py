"""C04 - volatility-scaled exposure overlay (capped at 1x) on C01.

Pre-registered in docs/research/evidence-review-2026-10/02-strategy-candidates.md (C04) and
reported in docs/research/05-first-candidates.md. Entries, exits and the catastrophe stop are
C01's, unchanged. Only the position size differs:

    stake = total equity x max_fraction x min(1, sigma_target / sigma_realised)

sigma_realised is the annualised (sqrt 365) standard deviation of daily log returns over
``vol_window_days``, read from the signal candle. While a trade is open the position is only
ever *scaled down*: when its value exceeds the current target by more than ``band`` (relative),
it is sold down to the target, provided the reduction is at least the exchange minimum order
cost. It is never scaled up (no adds), so exposure can only fall after entry.

Judge this on drawdown and vol-of-vol, not return (pre-registered in C04).

Tunable parameters (6): C01's lookback_days and catastrophe stop, plus sigma_target,
vol_window_days, band, max_fraction. Defaults, not tuned.
"""

import math

import numpy as np
from C01Tsmom1d import C01Tsmom1d  # sibling file; Freqtrade's documented inheritance pattern
from pandas import DataFrame


class C04TsmomVolScaled1d(C01Tsmom1d):
    sigma_target = 0.20
    vol_window_days = 30
    band = 0.25
    max_fraction = 0.5

    position_adjustment_enable = True
    max_entry_position_adjustment = 0  # scale-downs only; no additional entries

    startup_candle_count = max(C01Tsmom1d.lookback_days, vol_window_days) + 5

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        logret = np.log(dataframe["close"] / dataframe["close"].shift(1))
        dataframe["vol_ann"] = logret.rolling(self.vol_window_days).std() * math.sqrt(365)
        return dataframe

    def _target_stake(self, pair: str) -> float | None:
        df, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
        if df is None or df.empty:
            return None
        vol = float(df.iloc[-1]["vol_ann"])
        if not math.isfinite(vol) or vol <= 0:
            return None
        equity = self.wallets.get_total_stake_amount()
        return equity * self.max_fraction * min(1.0, self.sigma_target / vol)

    def custom_stake_amount(
        self, pair, current_time, current_rate, proposed_stake, min_stake, max_stake,
        leverage, entry_tag, side, **kwargs,
    ) -> float:
        target = self._target_stake(pair)
        if target is None:
            return 0.0  # no volatility estimate yet: do not trade
        return min(target, max_stake)

    def adjust_trade_position(
        self, trade, current_time, current_rate, current_profit, min_stake, max_stake,
        current_entry_rate, current_exit_rate, current_entry_profit, current_exit_profit,
        **kwargs,
    ) -> float | None:
        target = self._target_stake(trade.pair)
        if target is None:
            return None
        value = trade.amount * current_rate
        if value <= target * (1 + self.band):
            return None
        reduce = value - target
        if reduce < (min_stake or 0.0) or reduce >= value:
            return None
        return -reduce
