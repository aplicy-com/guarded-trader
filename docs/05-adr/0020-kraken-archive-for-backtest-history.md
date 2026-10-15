# ADR-0020: Kraken's official OHLCVT archive is the backtest data source; Binance is cross-check only

## Status

Accepted — 2026-10-14. **Supersedes [ADR-0010](0010-binance-ohlcv-for-backtest-history.md).**

## Context and problem statement

ADR-0010 sourced backtest history from Binance for one reason: Kraken's REST OHLC endpoint
serves only the latest ~720 candles (~4 months of 4h), and rebuilding candles from Kraken's
trade history was benchmarked at days of download. Two things have changed since
(`docs/research/evidence-review-2026-10/01-evidence-review.md` Q6):

1. **Kraken now publishes an official, free bulk OHLCVT archive** (support article
   360047124832): every pair from its first Kraken trade, 1/5/15/30/60/240/720/1440-minute
   candles, as a full-history zip split into ~2 GB parts with published SHA-256 checksums, plus
   quarterly incremental zips. That removes the reason ADR-0010 existed.
2. **Binance Vision's Terms of Use (v1.0, 26 Aug 2026)** license its datasets CC BY-NC-SA 4.0,
   permit "algorithmic historical backtesting for purely personal non-production research",
   prohibit use "for live proprietary trading execution", and claim anything "derived from"
   the data, including models. Whether a strategy backtested on Binance data and then traded
   on Kraken is a prohibited derivative is unresolved, as is whether the terms also cover the
   REST `klines` endpoint ADR-0010 used. Binance also left Canada on 2023-09-30.

Backtesting on the venue we trade on also removes ADR-0010's two accepted divergences
(cross-venue price differences and USDT-vs-USD quoting).

## Decision drivers

- The promotion path must not depend on data whose licence may prohibit exactly that use.
- Backtests should see the prices, wicks and gaps of the venue that will fill the orders.
- Multi-year 4h and 1d history covering both the 2022 bear and the 2025–26 drawdown.
- No paid provider, no API key, no data committed to the repo (unchanged from ADR-0010).
- Every file verifiable against a checksum, so a silently replaced file is detected.

## Considered options

- **Kraken official archive as the only promotion-path source; Binance as an optional,
  private cross-check** (chosen)
- Keep ADR-0010 (Binance for history)
- Kraken archive and Binance side by side as equal sources
- Rebuild candles from Kraken trade history (`--dl-trades`)

## Decision outcome

Chosen: **Kraken's archive is the source for every backtest on the promotion path** (Gate 1
and anything after it). Binance data may be used only to cross-check Kraken candles, privately,
within Binance Vision's personal non-production research permission, and is never committed,
redistributed, or used to score a candidate.

### How

`scripts/kraken_archive.py` (`make kraken-data`):

1. `download`: the five full-history parts and the quarterly incrementals listed in
   `scripts/kraken_archive_checksums.json`, resumable. ~10 GB.
2. `verify`: SHA-256 of every part against Kraken's published sums, the reassembled zip
   (streamed, never written) against Kraken's published full-zip hash, and each incremental
   against a pinned value. Kraken publishes no hash for incrementals, so theirs are pinned at
   first download (trust on first use) and any later change is caught.
3. `convert`, in a `--network none` container with the archive read-only: read each
   whitelisted pair's 240- and 1440-minute CSV directly out of the zips, union the full history
   with the incrementals, and **fail** on: timestamps off the interval grid, non-increasing
   timestamps, OHLC that is not internally consistent, non-positive prices, or a timestamp on
   which two archives disagree. Write Freqtrade feather files to `user_data/data/kraken/` and a
   `kraken-archive-report.json` recording the source hashes, each archive's `MANIFEST.json`,
   per-series row counts, missing intervals, the widest bars, each output file's SHA-256, and a
   `data_snapshot_id` that the research harness stamps on every trial.
4. `crossval` (optional): Kraken vs Binance closes on overlapping bars.

### Facts established on 2026-10-14

| Check | Result |
|---|---|
| All five parts, the reassembled full zip, and the 2026Q3 incremental | SHA-256 match |
| Full-archive coverage (its `MANIFEST.json`) | 2013-09-11 → **2026-09-30**, not 30 June as the support page says; the Q3 incremental is therefore already contained in it and merged with **zero** conflicting candles |
| Timestamp convention | Unix seconds at the candle **open**, as Freqtrade expects: 720 daily candles per pair from Kraken's REST endpoint (fetched 2026-09-09) match the archive **exactly** (max relative difference 0.0 on open and close) |
| Pair names | `BTC/USD` is `XBTUSD`; the other five are `ETHUSD`, `SOLUSD`, `XRPUSD`, `LINKUSD`, `LTCUSD` |
| History available | BTC from 2013-10, LTC 2013-10, ETH 2015-08, XRP 2017-05, LINK 2019-09, SOL 2021-06-17 |
| Missing candles from 2021-01-01 | 0 on 1d; 2–3 per pair on 4h (Freqtrade fills these itself on load). Earlier years have more (LTC 4h: 3,543 in total, mostly 2013–2017) |
| Kraken vs Binance (4h, 2024-09-09 → 2026-09-09, 4,379 bars per pair) | median absolute close difference 0.04–0.07 %; 0.09–0.11 % of bars differ by more than 0.5 %; worst 1.3–1.5 % |
| Venue-local wicks | Kraken's 2025-10-10 20:00 UTC 4h bar has a high-low range of ~60 % of close on LINK/USD and ~55 % on XRP/USD. Kept as Kraken printed it: that is what a Kraken stop would have met |

### Consequences

**Good:**
- Backtests run on the execution venue's own prices; ADR-0010's USD/USDT and cross-venue caveats
  no longer apply to any promotion decision.
- ~5 years of history after warm-up on all six pairs (SOL from mid-2021), enough for a canonical
  timerange containing both the 2022 bear and the 2025–26 drawdown.
- Every candle file is traceable to a verified Kraken archive by hash.

**Bad / accepted trade-offs:**
- **The archive states no licence.** Kraken's support page links only its general Terms of
  Service. We use it for private backtesting and never redistribute it; whether that use is
  covered is TBD (Phase 3) — the operator to ask Kraken support in writing.
- Quarterly lag: the newest archive data trails real time by up to a quarter. The REST endpoint
  (~720 candles) covers that gap if a backtest ever needs it (`make download-data`); the current
  canonical timerange ends at the archive's last full day, so it does not.
- A ~10 GB download per archive release. Only the converted feather files (a few MB) are needed
  afterwards; the archive itself can be deleted and re-downloaded.
- Kraken omits intervals with no trades; Freqtrade fills them with flat, zero-volume candles on
  load. Negligible after 2021 (above).

## More information

- Supersedes ADR-0010 for every purpose. The Binance-sourced numbers in
  `docs/research/03-baseline-backtest.md` remain as a historical record, not as evidence on the
  promotion path.
- Refresh procedure: [`docs/06-runbooks/refresh-backtest-data.md`](../06-runbooks/refresh-backtest-data.md).
- The research harness and gates that consume this data:
  [ADR-0021](0021-cost-consistent-gate-1-and-random-entry-null.md).
