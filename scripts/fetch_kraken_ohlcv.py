#!/usr/bin/env python3
"""Fetch Kraken OHLCV candles for the Phase 2 baseline backtest (work
package 2C, `docs/phase-2-plan.md`).

Why this script exists instead of `freqtrade download-data`: Kraken's
public OHLC endpoint does not serve historic klines — it always returns
only its own rolling window of the most recent candles regardless of the
`since` timestamp requested (confirmed empirically: a `since` of two years
ago on the 4h timeframe still returns only the trailing ~720 candles,
~120 days). Freqtrade knows this (`exchange.get_option("ohlcv_has_history")`
is `False` for Kraken) and its `download-data` CLI refuses to run at all
in klines mode for this exchange, directing you to `--dl-trades` instead
(reconstruct OHLCV from raw trade history). `--dl-trades` was tested
against this repo's actual whitelist pairs before writing this script: a
plain `fetch_trades` benchmark against live BTC/USD trade flow measured
~1000 trades per ~2.4s call: extrapolated, 30 days of BTC/USD trade
history alone would take on the order of two hours, and a full 730-day /
6-pair pull would take on the order of days — infeasible for this work
package and not something to run unattended overnight into a session with
no supervision.

So: this script pulls the maximum real history Kraken's public klines
endpoint actually serves (no synthetic/interpolated data, no paid
provider — consistent with the phase-2-plan.md §1 data-source decision),
for both `4h` and `1d`, and writes it via Freqtrade's own
`IDataHandler.ohlcv_store` so the on-disk format is exactly what
`freqtrade backtesting` expects. The realistic outcome, and the reason
`docs/research/03-baseline-backtest.md` reports actual coverage per
timeframe instead of a flat "2 years": 1d gets close to two years
(~720 daily candles); 4h gets roughly four months (~720 four-hour
candles) — both timeframes are capped at the same ~720-candle
Kraken-side window, so 4h's shorter per-candle duration means much less
wall-clock coverage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ccxt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DRY_RUN_CONFIG = REPO_ROOT / "services" / "freqtrade" / "user_data" / "config.dry_run.json"
DATADIR = REPO_ROOT / "services" / "freqtrade" / "user_data" / "data" / "kraken"

DEFAULT_TIMEFRAMES = ["4h", "1d"]
DEFAULT_DAYS = 730
KRAKEN_MAX_CANDLES_PER_CALL = 720  # Kraken's own server-side OHLC window.


def load_pairs() -> list[str]:
    config = json.loads(DRY_RUN_CONFIG.read_text())
    return config["exchange"]["pair_whitelist"]


def fetch_pair_timeframe(exchange: ccxt.kraken, pair: str, timeframe: str, days: int) -> pd.DataFrame:
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    candles = exchange.fetch_ohlcv(
        pair, timeframe=timeframe, since=since, limit=KRAKEN_MAX_CANDLES_PER_CALL
    )
    df = pd.DataFrame(
        candles, columns=["date", "open", "high", "low", "close", "volume"]
    )
    df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES)
    args = parser.parse_args()

    # Imported here so the script's docstring/CLI work without the
    # freqtrade package installed (e.g. `python3 --help` outside Docker).
    from freqtrade.data.history.datahandlers.idatahandler import get_datahandler
    from freqtrade.enums import CandleType

    pairs = load_pairs()
    exchange = ccxt.kraken({"enableRateLimit": True})
    exchange.load_markets()
    data_handler = get_datahandler(DATADIR, data_format="feather")

    for pair in pairs:
        for timeframe in args.timeframes:
            print(f"fetching {pair} {timeframe}...", file=sys.stderr)
            df = fetch_pair_timeframe(exchange, pair, timeframe, args.days)
            if df.empty:
                print(f"warning: no candles returned for {pair} {timeframe}", file=sys.stderr)
                continue
            data_handler.ohlcv_store(pair, timeframe, df, CandleType.SPOT)
            span_days = (df["date"].iloc[-1] - df["date"].iloc[0]).total_seconds() / 86400
            print(
                f"  wrote {len(df)} candles, {df['date'].iloc[0]} -> "
                f"{df['date'].iloc[-1]} ({span_days:.1f} days)",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
