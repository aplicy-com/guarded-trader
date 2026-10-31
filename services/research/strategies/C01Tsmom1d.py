"""C01 - weekly-scale time-series momentum, long-flat, trend-flip exit, daily bars.

Pre-registered in docs/research/evidence-review-2026-10/02-strategy-candidates.md (C01) and
reported in docs/research/05-first-candidates.md.

- Entry, at the daily close: the pair's L-day return is positive AND the pair ranks in the top
  ``max_slots`` of the whitelist by L-day return (so when more than two pairs qualify, the two
  strongest are the ones eligible).
- Exit, at the daily close: the L-day return is <= 0 (signal flip). Filled at the next open.
- Stop: -20% catastrophe stop only.
- Sizing: Freqtrade's equal split of the wallet over ``max_open_trades`` (2) = 0.5 per slot.

Cross-pair ranking reads the other pairs' candles for the *same* date through the
DataProvider; nothing later than the signal candle is used.

Tunable parameters (4): lookback_days, eval timeframe (fixed 1d), catastrophe stop,
slot fraction (via max_open_trades). Defaults, not tuned.
"""

import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class C01Tsmom1d(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"

    lookback_days = 21
    max_slots = 2

    minimal_roi = {"0": 10.0}
    stoploss = -0.20

    can_short = False
    process_only_new_candles = True
    startup_candle_count = lookback_days + 5

    def _momentum(self, dataframe: DataFrame) -> DataFrame:
        return dataframe["close"] / dataframe["close"].shift(self.lookback_days) - 1

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["mom"] = self._momentum(dataframe)
        stronger = np.zeros(len(dataframe), dtype=int)
        for other in self.dp.current_whitelist():
            if other == metadata["pair"]:
                continue
            odf = self.dp.get_pair_dataframe(pair=other, timeframe=self.timeframe)
            if odf is None or odf.empty:
                continue
            omom = self._momentum(odf).set_axis(odf["date"])
            aligned = omom.reindex(dataframe["date"]).to_numpy()
            stronger += np.nan_to_num(aligned > dataframe["mom"].to_numpy(), nan=0).astype(int)
        dataframe["mom_rank"] = 1 + stronger
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["mom"] > 0) & (dataframe["mom_rank"] <= self.max_slots) & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["mom"] <= 0, "exit_long"] = 1
        return dataframe
