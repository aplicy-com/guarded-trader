#!/usr/bin/env python3
"""Pull Kraken market facts for the Phase 2 pair whitelist decision.

Public ccxt endpoints only — no API key, no exchange authentication.
Resolves the phase-2-plan.md §2 (2B) TBDs: confirms a $30/position stake
(dry_run_wallet 100 / max_open_trades 3, rounded down for headroom) clears
every exchange minimum, and applies the R5 account-isolation exclusion
list read from services/freqtrade/user_data/config.dry_run.json so the
held-asset blacklist can't drift out of sync between the two files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import ccxt

REPO_ROOT = Path(__file__).resolve().parent.parent
DRY_RUN_CONFIG = REPO_ROOT / "services" / "freqtrade" / "user_data" / "config.dry_run.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "research" / "02-kraken-market-facts.md"

CANDIDATES = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
    "LINK/USD",
    "AVAX/USD",
    "LTC/USD",
    "DOT/USD",  # included only to demonstrate the R5 blacklist check fails it
]

# $100 principal / 3 max_open_trades = $33.33; round down to $30 for
# headroom so the check is conservative rather than exactly-on-the-line.
STAKE_USD = 30.0
HEADROOM = 1.20
OHLCV_DAYS = 30
MAX_RECOMMENDED = 6


def load_held_assets() -> set[str]:
    """Read the R5 held-asset exclusion list from the dry-run config's
    pair_blacklist, so this script and Freqtrade can't silently diverge."""
    config = json.loads(DRY_RUN_CONFIG.read_text())
    patterns = config["exchange"]["pair_blacklist"]
    return {re.match(r"^([A-Z0-9]+)/", p).group(1) for p in patterns}


def fetch_30d_volume_usd(exchange: ccxt.kraken, symbol: str) -> float:
    """Sum of daily (base_volume * close) over the last OHLCV_DAYS complete
    days. Fetches one extra candle and drops it, since the most recent
    candle from fetch_ohlcv is usually the current, incomplete day."""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1d", limit=OHLCV_DAYS + 1)
    complete_days = ohlcv[:-1] if len(ohlcv) > OHLCV_DAYS else ohlcv
    return sum(close * volume for _, _open, _high, _low, close, volume in complete_days)


def facts_for_pair(exchange: ccxt.kraken, symbol: str, held_assets: set[str]) -> dict:
    market = exchange.markets[symbol]
    base = market["base"]

    min_amount = market["limits"]["amount"]["min"]
    min_cost = market["limits"]["cost"]["min"]
    price_precision = market["precision"]["price"]
    amount_precision = market["precision"]["amount"]
    maker_fee = market["maker"]
    taker_fee = market["taker"]

    ticker = exchange.fetch_ticker(symbol)
    last_price = ticker["last"]

    volume_30d_usd = fetch_30d_volume_usd(exchange, symbol)

    min_cost_from_amount = min_amount * last_price if last_price else None
    effective_min_cost = max(
        c for c in (min_cost, min_cost_from_amount) if c is not None
    )
    clears_headroom = STAKE_USD >= effective_min_cost * HEADROOM

    r5_excluded = base in held_assets

    return {
        "symbol": symbol,
        "base": base,
        "last_price": last_price,
        "min_amount": min_amount,
        "min_cost": min_cost,
        "price_precision": price_precision,
        "amount_precision": amount_precision,
        "maker_fee": maker_fee,
        "taker_fee": taker_fee,
        "volume_30d_usd": volume_30d_usd,
        "effective_min_cost_usd": effective_min_cost,
        "clears_headroom": clears_headroom,
        "r5_excluded": r5_excluded,
    }


def render_markdown(rows: list[dict], held_assets: set[str]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append("# Kraken market facts — Phase 2 pair whitelist")
    lines.append("")
    lines.append(
        f"Generated {generated_at} by `scripts/kraken_market_facts.py` against "
        "Kraken's public ccxt endpoints (no API key). Resolves the phase-2-plan.md "
        "§2 (2B) TBDs on minimum order sizes, pair universe, and the $30/position "
        "sizing check."
    )
    lines.append("")
    lines.append(
        f"**Stake assumption:** ${STAKE_USD:.0f} per position "
        f"(${100:.0f} principal / 3 max_open_trades ≈ $33.33, rounded down for "
        f"headroom). A pair clears sizing if ${STAKE_USD:.0f} ≥ "
        f"{HEADROOM:.0%} of its effective minimum notional (the larger of "
        "Kraken's `costmin` and `ordermin × last price`)."
    )
    lines.append("")

    lines.append("## Market facts")
    lines.append("")
    lines.append(
        "| Pair | Last price (USD) | Min amount | Min cost (USD) | "
        "Price precision | Amount precision | Maker fee | Taker fee | "
        "30d volume (USD) | $30 stake clears w/ 20% headroom |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    for r in rows:
        clears = "✅ yes" if r["clears_headroom"] else "❌ no"
        lines.append(
            f"| {r['symbol']} | {r['last_price']:,.4f} | "
            f"{r['min_amount']:g} | {r['min_cost']:,.4f} | "
            f"{r['price_precision']:g} | {r['amount_precision']:g} | "
            f"{r['maker_fee']:.4%} | {r['taker_fee']:.4%} | "
            f"{r['volume_30d_usd']:,.0f} | {clears} |"
        )
    lines.append("")

    lines.append("## R5 account-isolation exclusion")
    lines.append("")
    lines.append(
        "The following base assets are pre-existing personal holdings on this "
        "Kraken account (bought before this project, gifted, or otherwise not "
        "system-acquired). Per R5 (`docs/02-requirements.md`), the system may "
        "only size and reconcile assets it bought itself — these are excluded "
        "from the tradable whitelist regardless of market quality, and the "
        "list is read directly from "
        "`services/freqtrade/user_data/config.dry_run.json`'s `pair_blacklist` "
        "so the two can't drift apart."
    )
    lines.append("")
    lines.append(f"Held assets (R5 blacklist): {', '.join(sorted(held_assets))}")
    lines.append("")
    excluded_rows = [r for r in rows if r["r5_excluded"]]
    if excluded_rows:
        lines.append("Candidates excluded by this check:")
        lines.append("")
        for r in excluded_rows:
            lines.append(
                f"- **{r['symbol']}** — excluded: `{r['base']}` is in the R5 "
                "held-asset blacklist (pre-existing balance, not system-bought)."
            )
    else:
        lines.append("None of the candidates were excluded by this check.")
    lines.append("")

    eligible = [r for r in rows if not r["r5_excluded"]]
    sizing_failures = [r for r in eligible if not r["clears_headroom"]]
    if sizing_failures:
        lines.append(
            "The following R5-eligible candidates were also dropped because they "
            "do not clear the $30 stake / 20% headroom check:"
        )
        lines.append("")
        for r in sizing_failures:
            lines.append(
                f"- **{r['symbol']}** — effective min notional "
                f"${r['effective_min_cost_usd']:,.2f}, needs "
                f"${r['effective_min_cost_usd'] * HEADROOM:,.2f} with headroom, "
                f"exceeds the ${STAKE_USD:.0f} stake."
            )
        lines.append("")

    recommended = sorted(
        (r for r in eligible if r["clears_headroom"]),
        key=lambda r: r["volume_30d_usd"],
        reverse=True,
    )[:MAX_RECOMMENDED]

    lines.append("## Recommended final whitelist")
    lines.append("")
    lines.append(
        f"Top {len(recommended)} of the R5-eligible, sizing-eligible candidates "
        "by 30-day USD volume:"
    )
    lines.append("")
    for r in recommended:
        lines.append(f"- {r['symbol']} — 30d volume ${r['volume_30d_usd']:,.0f}")
    lines.append("")
    lines.append(
        "```json\n"
        + json.dumps([r["symbol"] for r in recommended], indent=2)
        + "\n```"
    )
    lines.append("")

    lines.append("## Resolved TBDs")
    lines.append("")
    lines.append(
        "- Minimum order sizes and notional confirmed live from Kraken via ccxt "
        "(table above) — no longer `TBD (Phase 2)`."
    )
    lines.append(
        f"- Pair universe: recommended whitelist above ({len(recommended)} pairs) "
        "supersedes the draft 3-pair list in phase-2-plan.md §1."
    )
    lines.append(
        f"- $100 sizing check: confirmed — every recommended pair clears a "
        f"${STAKE_USD:.0f} stake with {HEADROOM:.0%} headroom above its "
        "effective minimum notional."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output markdown path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args()

    held_assets = load_held_assets()

    exchange = ccxt.kraken({"enableRateLimit": True})
    exchange.load_markets()

    rows = []
    for symbol in CANDIDATES:
        if symbol not in exchange.markets:
            print(f"warning: {symbol} not found on Kraken, skipping", file=sys.stderr)
            continue
        print(f"fetching {symbol}...", file=sys.stderr)
        rows.append(facts_for_pair(exchange, symbol, held_assets))

    markdown = render_markdown(rows, held_assets)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
