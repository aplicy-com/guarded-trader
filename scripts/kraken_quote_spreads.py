"""Measure Kraken's live quote-currency costs for round 2 (public endpoints only; no API key).

    python3 -I scripts/kraken_quote_spreads.py --samples 20 --interval 15 > out.json

For BTC and ETH in USD and CAD, and for the cash pair USD/CAD, samples the top-of-book spread
and walks the order book to price a market buy of a given notional (the "impact" beyond the
mid). Also records each pair's ordermin/costmin. Read-only: Ticker, Depth and AssetPairs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from datetime import UTC, datetime

API = "https://api.kraken.com/0/public"
PAIRS = {"BTC/USD": "XBTUSD", "BTC/CAD": "XBTCAD", "ETH/USD": "ETHUSD", "ETH/CAD": "ETHCAD", "USD/CAD": "USDCAD"}


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}/{path}", timeout=20) as r:  # noqa: S310 (fixed https host)
        body = json.load(r)
    if body["error"]:
        raise RuntimeError(body["error"])
    return body["result"]


def walk(asks: list[list[str]], notional: float) -> float | None:
    """Average fill price of a market buy spending ``notional`` quote; None if the book is short."""
    spent = qty = 0.0
    for px, vol, *_ in asks:
        p, v = float(px), float(vol)
        take = min(v, (notional - spent) / p)
        spent += take * p
        qty += take
        if spent >= notional - 1e-9:
            return spent / qty
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--interval", type=float, default=15.0)
    args = ap.parse_args()
    meta = get("AssetPairs?pair=" + ",".join(PAIRS.values()))
    alt_of = {key: m["altname"] for key, m in meta.items()}  # XXBTZUSD -> XBTUSD
    by_alt = {m["altname"]: m for m in meta.values()}
    samples: dict[str, list[dict]] = {p: [] for p in PAIRS}
    usdcad = None
    for i in range(args.samples):
        tick = {alt_of[k]: v for k, v in get("Ticker?pair=" + ",".join(PAIRS.values())).items()}
        t = tick["USDCAD"]
        usdcad = (float(t["b"][0]) + float(t["a"][0])) / 2
        for pair, alt in PAIRS.items():
            t = tick[alt]
            bid, ask = float(t["b"][0]), float(t["a"][0])
            mid = (bid + ask) / 2
            asks = next(iter(get(f"Depth?pair={alt}&count=100").values()))["asks"]
            row = {"bid": bid, "ask": ask, "spread_bp": (ask - bid) / mid * 1e4}
            for usd in (25.0, 100.0):
                # Notional in the pair's quote currency: CAD pairs (incl. USD/CAD) spend usd * USDCAD.
                notional = usd * usdcad if pair.endswith("/CAD") else usd
                avg = walk(asks, notional)
                row[f"buy_{int(usd)}usd_vs_mid_bp"] = None if avg is None else (avg / mid - 1) * 1e4
            samples[pair].append(row)
        if i < args.samples - 1:
            time.sleep(args.interval)
    out = {
        "measured_at_end": datetime.now(UTC).isoformat(timespec="seconds"),
        "samples": args.samples,
        "interval_s": args.interval,
        "usdcad_mid_last": usdcad,
        "pairs": {},
    }
    for pair, alt in PAIRS.items():
        rows, m = samples[pair], by_alt[alt]
        sp = [r["spread_bp"] for r in rows]
        out["pairs"][pair] = {
            "kraken_pair": alt,
            "ordermin_base": float(m["ordermin"]),
            "costmin_quote": float(m.get("costmin") or 0),
            "spread_bp_median": statistics.median(sp),
            "spread_bp_max": max(sp),
            "buy_25usd_vs_mid_bp_median": statistics.median(r["buy_25usd_vs_mid_bp"] for r in rows),
            "buy_100usd_vs_mid_bp_median": statistics.median(r["buy_100usd_vs_mid_bp"] for r in rows),
            "last_mid": (rows[-1]["bid"] + rows[-1]["ask"]) / 2,
        }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
