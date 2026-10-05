#!/usr/bin/env python3
"""Check that the live pilot's real stake clears Kraken's minimums on every whitelisted pair.

Reads services/freqtrade/user_data/config.live.json (whitelist, blacklist, max_open_trades,
available_capital), pulls Kraken's public market limits and last prices (no API key), and fails
(exit 1) unless the per-position stake clears each pair's effective minimum with headroom.

Stake per position = available_capital / max_open_trades (Freqtrade's "unlimited" stake with
available_capital). Effective minimum = max(costmin, ordermin x price) x the stoploss reserve
Freqtrade adds on top (capped at 1.5x: freqtrade/exchange/exchange.py, _get_stake_amount_limit,
for a strategy whose static stoploss is -0.99 like Baseline4h). HEADROOM is applied on top of that.

    uv run --with ccxt scripts/kraken_pilot_sizing.py [--out docs/research/04-live-pilot-sizing.md]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_CONFIG = REPO_ROOT / "services" / "freqtrade" / "user_data" / "config.live.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "research" / "04-live-pilot-sizing.md"

STOPLOSS_RESERVE = 1.5  # Freqtrade's cap on (5% margin) / (1 - |stoploss|)
HEADROOM = 1.2  # extra safety on top of the reserve, as in 02-kraken-market-facts.md
# Assets the operator holds on the account already (R5). ADR-0019 / config.live.json blacklist.
HELD_ASSETS = {"ADA", "ETH", "DOT", "SC", "KAVA", "ACA", "XTZ", "USDC"}


@dataclass(frozen=True)
class PairFacts:
    symbol: str
    last_price: float
    min_amount: float
    min_cost: float | None


@dataclass(frozen=True)
class SizingRow:
    symbol: str
    last_price: float
    effective_min_usd: float  # exchange minimum notional, before Freqtrade's reserve
    required_stake_usd: float  # x reserve x headroom
    stake_usd: float
    clears: bool
    headroom_x: float  # stake / (effective min x reserve)


def stake_per_position(available_capital: float, max_open_trades: int) -> float:
    if max_open_trades < 1 or available_capital <= 0:
        raise ValueError("max_open_trades must be >= 1 and available_capital > 0")
    return available_capital / max_open_trades


def size_pair(f: PairFacts, stake: float) -> SizingRow:
    candidates = [c for c in (f.min_cost, f.min_amount * f.last_price) if c is not None]
    eff = max(candidates)
    reserved = eff * STOPLOSS_RESERVE
    return SizingRow(
        f.symbol, f.last_price, eff, reserved * HEADROOM, stake, stake >= reserved * HEADROOM,
        stake / reserved,
    )  # fmt: skip


def blacklisted_bases(patterns: list[str]) -> set[str]:
    return {m.group(1) for p in patterns if (m := re.match(r"^([A-Z0-9]+)/", p))}


def validate_config(config: dict) -> list[str]:
    """Static problems with the live config, independent of market data."""
    problems: list[str] = []
    ex = config["exchange"]
    if config.get("dry_run") is not False:
        problems.append("dry_run must be false in the live config")
    if config.get("initial_state") != "paused":
        problems.append("initial_state must be 'paused' (ADR-0018)")
    held = blacklisted_bases(ex["pair_blacklist"])
    missing = HELD_ASSETS - held
    if missing:
        problems.append(f"held assets not blacklisted: {sorted(missing)}")
    for pair in ex["pair_whitelist"]:
        base = pair.split("/")[0]
        if base in HELD_ASSETS:
            problems.append(f"{pair} is whitelisted but {base} is a held asset (R5)")
    return problems


def render(rows: list[SizingRow], config: dict, problems: list[str]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stake = rows[0].stake_usd if rows else 0.0
    out = [
        "# Live pilot sizing check",
        "",
        f"Generated {now} by `scripts/kraken_pilot_sizing.py` from `config.live.json` and Kraken's "
        "public endpoints (no API key).",
        "",
        f"**Stake:** available_capital {config['available_capital']} USD / max_open_trades "
        f"{config['max_open_trades']} = **{stake:.2f} USD per position**. A pair passes if the "
        f"stake >= {STOPLOSS_RESERVE}x (Freqtrade stoploss reserve) x {HEADROOM}x (headroom) x "
        "its exchange minimum notional.",
        "",
        "| Pair | Last (USD) | Exchange min notional (USD) | Needed stake (USD) | Stake / (min x reserve) | Pass |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r.symbol} | {r.last_price:,.4f} | {r.effective_min_usd:.2f} | "
            f"{r.required_stake_usd:.2f} | {r.headroom_x:.2f}x | {'yes' if r.clears else '**NO**'} |"
        )
    out += ["", "## Config checks", ""]
    out += [f"- FAIL: {p}" for p in problems] or ["- all static checks pass"]
    out += ["", f"**Result: {'FAIL' if problems or not all(r.clears for r in rows) else 'PASS'}**", ""]
    return "\n".join(out)


def fetch_facts(symbols: list[str]) -> list[PairFacts]:
    import ccxt  # imported late so the pure functions are testable without it

    exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 20000})
    exchange.load_markets()
    facts = []
    for s in symbols:
        m = exchange.markets[s]
        facts.append(
            PairFacts(
                s,
                float(exchange.fetch_ticker(s)["last"]),
                float(m["limits"]["amount"]["min"]),
                None if m["limits"]["cost"]["min"] is None else float(m["limits"]["cost"]["min"]),
            )
        )
    return facts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=LIVE_CONFIG)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    config = json.loads(args.config.read_text())
    stake = stake_per_position(config["available_capital"], config["max_open_trades"])
    rows = [size_pair(f, stake) for f in fetch_facts(config["exchange"]["pair_whitelist"])]
    problems = validate_config(config)
    text = render(rows, config, problems)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(text)
    return 1 if problems or not all(r.clears for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
