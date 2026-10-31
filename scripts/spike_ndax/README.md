# NDAX feasibility probes (spike/ndax)

Public endpoints only: no API key, no `.env`. Each script runs in the pinned Freqtrade image
so it uses the same ccxt (4.5.76) the bot would:

```bash
docker run --rm -v "$PWD/scripts/spike_ndax:/probe:ro" --entrypoint python \
  freqtradeorg/freqtrade:2026.8 /probe/01_markets_books.py
```

| Script | What it checks |
|---|---|
| `01_markets_books.py` | `has` flags, markets, minimums, 4h/1d OHLCV, order-book spread and depth, fee API |
| `02_spreads_history.py` | Spread stability (3 samples), USD vs CAD books, 1d history depth and gaps |
| `03_4h_depth_and_labels.py` | 4h history depth and gaps; whether candles are labelled by open or close time |

Findings: [`docs/research/06-ndax-feasibility.md`](../../docs/research/06-ndax-feasibility.md).
Spike code: not part of the trading path, not wired into any make target.
