# Kraken market facts — Phase 2 pair whitelist

Generated 2026-09-09 16:49 UTC by `scripts/kraken_market_facts.py` against Kraken's public ccxt endpoints (no API key). Resolves the phase-2-plan.md §2 (2B) TBDs on minimum order sizes, pair universe, and the $30/position sizing check.

**Stake assumption:** $30 per position ($100 principal / 3 max_open_trades ≈ $33.33, rounded down for headroom). A pair clears sizing if $30 ≥ 120% of its effective minimum notional (the larger of Kraken's `costmin` and `ordermin × last price`).

## Market facts

| Pair | Last price (USD) | Min amount | Min cost (USD) | Price precision | Amount precision | Maker fee | Taker fee | 30d volume (USD) | $30 stake clears w/ 20% headroom |
|---|---|---|---|---|---|---|---|---|---|
| BTC/USD | 78,732.4000 | 5e-05 | 0.5000 | 0.1 | 1e-08 | 0.1600% | 0.2600% | 5,512,978,976 | ✅ yes |
| ETH/USD | 2,495.9700 | 0.001 | 0.5000 | 0.01 | 1e-08 | 0.1600% | 0.2600% | 1,693,036,383 | ✅ yes |
| SOL/USD | 103.2900 | 0.06 | 0.5000 | 0.01 | 1e-08 | 0.1600% | 0.2600% | 1,013,193,763 | ✅ yes |
| XRP/USD | 1.4212 | 1.65 | 0.5000 | 1e-05 | 1e-08 | 0.1600% | 0.2600% | 1,744,872,702 | ✅ yes |
| LINK/USD | 12.0273 | 0.55 | 0.5000 | 1e-05 | 1e-08 | 0.1600% | 0.2600% | 169,534,048 | ✅ yes |
| AVAX/USD | 7.9510 | 0.5 | 0.5000 | 0.001 | 1e-08 | 0.1600% | 0.2600% | 61,725,043 | ✅ yes |
| LTC/USD | 54.1300 | 0.1 | 0.5000 | 0.01 | 1e-08 | 0.1600% | 0.2600% | 93,895,438 | ✅ yes |
| DOT/USD | 1.1276 | 3.9 | 0.5000 | 0.0001 | 1e-08 | 0.1600% | 0.2600% | 27,017,294 | ✅ yes |

## R5 account-isolation exclusion

The following base assets are pre-existing personal holdings on this Kraken account (bought before this project, gifted, or otherwise not system-acquired). Per R5 (`docs/02-requirements.md`), the system may only size and reconcile assets it bought itself — these are excluded from the tradable whitelist regardless of market quality, and the list is read directly from `services/freqtrade/user_data/config.dry_run.json`'s `pair_blacklist` so the two can't drift apart.

Held assets (R5 blacklist): ACA, ADA, DOT, KAVA, SC, XTZ

Candidates excluded by this check:

- **DOT/USD** — excluded: `DOT` is in the R5 held-asset blacklist (pre-existing balance, not system-bought).

## Recommended final whitelist

Top 6 of the R5-eligible, sizing-eligible candidates by 30-day USD volume:

- BTC/USD — 30d volume $5,512,978,976
- XRP/USD — 30d volume $1,744,872,702
- ETH/USD — 30d volume $1,693,036,383
- SOL/USD — 30d volume $1,013,193,763
- LINK/USD — 30d volume $169,534,048
- LTC/USD — 30d volume $93,895,438

```json
[
  "BTC/USD",
  "XRP/USD",
  "ETH/USD",
  "SOL/USD",
  "LINK/USD",
  "LTC/USD"
]
```

## Resolved TBDs

- Minimum order sizes and notional confirmed live from Kraken via ccxt (table above) — no longer `TBD (Phase 2)`.
- Pair universe: recommended whitelist above (6 pairs) supersedes the draft 3-pair list in phase-2-plan.md §1.
- $100 sizing check: confirmed — every recommended pair clears a $30 stake with 120% headroom above its effective minimum notional.
