"""Run Freqtrade backtests in-process, offline. Imported only inside the sandbox container.

The sandbox (scripts/research-harness.sh) has no network, so the exchange's market metadata
comes from a committed snapshot (services/research/fixtures/kraken-markets.json: public data
for the whitelisted pairs only) instead of a live ``load_markets`` call. Nothing here can reach
an order endpoint: there is no network, no key, and Freqtrade's Backtesting forces dry_run.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from freqtrade.configuration import Configuration
from freqtrade.configuration.timerange import TimeRange
from freqtrade.enums import RunMode
from freqtrade.exchange.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.util import dt_ts

logger = logging.getLogger(__name__)

EntryOverride = Callable[[pd.DataFrame, dict], pd.DataFrame]


def install_offline_markets(snapshot: Path) -> None:
    markets = json.loads(snapshot.read_text())["markets"]

    def reload_markets(self: Exchange, force: bool = False, *, load_leverage_tiers: bool = True) -> None:
        if self._last_markets_refresh > 0:
            return
        self._api.set_markets(markets)
        self._api_async.set_markets(markets)
        self._markets = self._api.markets
        self._last_markets_refresh = dt_ts()

    Exchange.reload_markets = reload_markets  # type: ignore[method-assign]


@dataclass(frozen=True)
class Paths:
    configs: list[Path]  # config.dry_run.json, config.backtest-costs.json
    strategy_path: Path
    datadir: Path
    user_data_dir: Path


@dataclass
class RunResult:
    trades: list[dict]
    final_balance: float
    starting_balance: float
    start: pd.Timestamp
    end: pd.Timestamp
    fee: float


class Session:
    """One strategy, one timerange, data loaded once; any number of entry variants."""

    def __init__(self, paths: Paths, strategy: str, timeframe: str, timerange: str, fee: float | None = None) -> None:
        args = {
            "config": [str(p) for p in paths.configs],
            "strategy": strategy,
            "strategy_path": str(paths.strategy_path),
            "datadir": str(paths.datadir),
            "user_data_dir": str(paths.user_data_dir),
            "timerange": timerange,
            "timeframe": timeframe,
            "export": "none",
            "cache": "none",
            "enable_protections": True,
        }
        if fee is not None:
            args["fee"] = fee
        self.config = Configuration(args, RunMode.BACKTEST).get_config()
        # Its credentials come from .env at runtime, which never enters the sandbox; a backtest
        # has no use for an API server anyway.
        self.config.pop("api_server", None)
        logging.getLogger("freqtrade").setLevel(logging.WARNING)  # Configuration resets it
        self.bt = Backtesting(self.config)
        self.data, self.timerange = self.bt.load_bt_data()
        self.strategy = self.bt.strategylist[0]
        self._original_entry = self.strategy.populate_entry_trend

    @property
    def fee(self) -> float:
        return float(self.bt.fee)

    def run(self, entry_override: EntryOverride | None = None) -> RunResult:
        self.strategy.populate_entry_trend = entry_override or self._original_entry  # type: ignore[method-assign]
        start, end = self.bt.backtest_one_strategy(self.strategy, self.data, self.timerange)
        content = self.bt.all_bt_content[self.strategy.get_strategy_name()]
        trades = content["results"].to_dict("records")
        return RunResult(
            trades=trades,
            final_balance=float(content["final_balance"]),
            starting_balance=float(self.config["dry_run_wallet"]),
            start=pd.Timestamp(start),
            end=pd.Timestamp(end),
            fee=self.fee,
        )

    def ohlcv(self) -> dict[str, pd.DataFrame]:
        return self.data

    def bars_in_range(self) -> dict[str, int]:
        tr: TimeRange = self.timerange
        out = {}
        for pair, df in self.data.items():
            d = df["date"]
            mask = pd.Series(True, index=df.index)
            if tr.starttype == "date":
                mask &= d >= tr.startdt
            if tr.stoptype == "date":
                mask &= d <= tr.stopdt
            out[pair] = int(mask.sum())
        return out
