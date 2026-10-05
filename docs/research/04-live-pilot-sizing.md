# Live pilot sizing check

Generated 2026-10-05 19:30 UTC by `scripts/kraken_pilot_sizing.py` from `config.live.json` and Kraken's public endpoints (no API key).

**Stake:** available_capital 19 USD / max_open_trades 1 = **19.00 USD per position**. A pair passes if the stake >= 1.5x (Freqtrade stoploss reserve) x 1.2x (headroom) x its exchange minimum notional.

| Pair | Last (USD) | Exchange min notional (USD) | Needed stake (USD) | Stake / (min x reserve) | Pass |
|---|---|---|---|---|---|
| BTC/USD | 85,698.6000 | 4.28 | 7.71 | 2.96x | yes |
| XRP/USD | 1.5016 | 2.48 | 4.46 | 5.11x | yes |
| SOL/USD | 120.0900 | 7.21 | 12.97 | 1.76x | yes |
| LINK/USD | 13.9468 | 7.67 | 13.81 | 1.65x | yes |
| LTC/USD | 70.2900 | 7.03 | 12.65 | 1.80x | yes |

## Config checks

- all static checks pass

**Result: PASS**
