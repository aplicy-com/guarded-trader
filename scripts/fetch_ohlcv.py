#!/usr/bin/env python3
"""Fetch OHLCV candles for the Phase 2 baseline backtest (work package 2C,
`docs/phase-2-plan.md`), from either Kraken (execution venue) or Binance
(backtest-history venue, see `docs/05-adr/0010-binance-ohlcv-for-backtest-history.md`).

`--venue kraken` (default) — kept for reference / re-verification. Kraken's
public OHLC endpoint does not serve historic klines at all: it always
returns only its own rolling window of the most recent candles, regardless
of the `since` timestamp requested (confirmed empirically: a `since` of
two years ago on the 4h timeframe still returns only the trailing ~720
candles, ~120 days). Freqtrade knows this
(`exchange.get_option("ohlcv_has_history")` is `False` for Kraken) and its
`download-data` CLI refuses to run at all in klines mode for this
exchange, directing you to `--dl-trades` instead (reconstruct OHLCV from
raw trade history) — benchmarked against this repo's actual pairs and
found infeasible (~2 hours for 30 days of BTC/USD trades alone; see
ADR-0010). This venue writes a single fetch per pair/timeframe: whatever
Kraken's rolling window actually contains, no more.

`--venue binance` — real historical pagination. Binance's OHLC endpoint
honours `since` for genuine multi-year lookback (verified live), so this
venue loops `fetch_ohlcv` calls forward from `since` until it reaches the
present or the exchange stops returning new candles. Binance's own `USD`
markets are effectively illiquid (checked live: `BTC/USD` ~$796K/day vs.
`BTC/USDT` ~$1.09B/day — see ADR-0010), so whitelisted `.../USD` pairs are
requested from Binance as their `.../USDT` equivalents.

Both venues write through Freqtrade's own `IDataHandler.ohlcv_store`, so
the on-disk format is exactly what `freqtrade backtesting` expects, into
a venue-named subdirectory (`user_data/data/kraken/`,
`user_data/data/binance/`) so the two are never silently mixed. Kraken
remains the sole execution venue regardless of which venue backtest
history came from (ADR-0010) — this script never touches order routing or
`config.dry_run.json`'s `exchange.name`.
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
DATA_ROOT = REPO_ROOT / "services" / "freqtrade" / "user_data" / "data"

DEFAULT_TIMEFRAMES = ["4h", "1d"]
DEFAULT_DAYS = 730
KRAKEN_MAX_CANDLES_PER_CALL = 720  # Kraken's own server-side OHLC window.
BINANCE_MAX_CANDLES_PER_CALL = 1000
BINANCE_MAX_PAGES = 20  # safety cap; 2y of 4h needs ~5 pages


def load_kraken_pairs() -> list[str]:
    config = json.loads(DRY_RUN_CONFIG.read_text())
    return config["exchange"]["pair_whitelist"]


def to_binance_pair(pair: str) -> str:
    """.../USD -> .../USDT — see ADR-0010 (Binance USD markets are
    effectively illiquid; USDT is the liquid, real-volume equivalent)."""
    base, quote = pair.split("/")
    return f"{base}/USDT" if quote == "USD" else pair


def fetch_kraken(exchange: ccxt.kraken, pair: str, timeframe: str, days: int) -> pd.DataFrame:
    """Single call — Kraken ignores `since` beyond its own rolling window,
    so pagination would just re-fetch the same trailing candles."""
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    candles = exchange.fetch_ohlcv(
        pair, timeframe=timeframe, since=since, limit=KRAKEN_MAX_CANDLES_PER_CALL
    )
    return _to_dataframe(candles)


def fetch_binance(exchange: ccxt.binance, pair: str, timeframe: str, days: int) -> pd.DataFrame:
    """Real pagination — Binance honours `since` for genuine historical
    lookback, so loop forward until we reach the present."""
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    all_candles: list[list] = []

    for _ in range(BINANCE_MAX_PAGES):
        batch = exchange.fetch_ohlcv(
            pair, timeframe=timeframe, since=since, limit=BINANCE_MAX_CANDLES_PER_CALL
        )
        if not batch:
            break
        all_candles.extend(batch)
        last_ts = batch[-1][0]
        next_since = last_ts + timeframe_ms
        if next_since <= since or next_since >= exchange.milliseconds():
            break
        since = next_since

    # Pages can overlap by one candle at the boundary; de-dupe by timestamp.
    dedup = {c[0]: c for c in all_candles}
    ordered = [dedup[ts] for ts in sorted(dedup)]
    return _to_dataframe(ordered)


def _to_dataframe(candles: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(candles, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
    return df


VENUES = {
    "kraken": {
        "exchange_cls": ccxt.kraken,
        "pairs_fn": load_kraken_pairs,
        "fetch_fn": fetch_kraken,
    },
    "binance": {
        "exchange_cls": ccxt.binance,
        "pairs_fn": lambda: [to_binance_pair(p) for p in load_kraken_pairs()],
        "fetch_fn": fetch_binance,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", choices=sorted(VENUES), default="kraken")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES)
    args = parser.parse_args()

    # Imported here so the script's docstring/CLI work without the
    # freqtrade package installed (e.g. `python3 --help` outside Docker).
    from freqtrade.data.history.datahandlers.idatahandler import get_datahandler
    from freqtrade.enums import CandleType

    venue = VENUES[args.venue]
    datadir = DATA_ROOT / args.venue
    pairs = venue["pairs_fn"]()
    exchange = venue["exchange_cls"]({"enableRateLimit": True})
    exchange.load_markets()
    data_handler = get_datahandler(datadir, data_format="feather")

    for pair in pairs:
        for timeframe in args.timeframes:
            print(f"[{args.venue}] fetching {pair} {timeframe}...", file=sys.stderr)
            df = venue["fetch_fn"](exchange, pair, timeframe, args.days)
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
