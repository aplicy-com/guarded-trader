"""Daily Kraken candles for round 2, read from the converted archive (ADR-0020). Sandbox only."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATADIR = Path("/repo/services/freqtrade/user_data/data/kraken")
REPORT = DATADIR / "kraken-archive-report.json"
PAIRS = ("BTC/USD", "ETH/USD")


def load_daily(pair: str, datadir: Path = DATADIR) -> pd.DataFrame:
    """Raw daily rows as Kraken printed them, indexed by the candle's UTC open day."""
    df = pd.read_feather(datadir / f"{pair.replace('/', '_')}-1d.feather")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date")[["open", "high", "low", "close", "volume"]].sort_index()


def complete_grid(raw: pd.DataFrame) -> pd.DataFrame:
    """Calendar-day grid; a missing day becomes a flat, zero-volume candle at the previous close
    (what Freqtrade does on load), so signals and fills see the last traded price."""
    days = pd.date_range(raw.index[0], raw.index[-1], freq="D", tz="UTC")
    out = raw.reindex(days)
    prev_close = out["close"].ffill()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].fillna(prev_close)
    out["volume"] = out["volume"].fillna(0.0)
    return out


def panel(datadir: Path = DATADIR) -> dict[str, pd.DataFrame]:
    return {p: complete_grid(load_daily(p, datadir)) for p in PAIRS}
