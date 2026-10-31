# ADR-0010: Source backtest OHLCV history from Binance, keep Kraken as the sole execution venue

## Status

Superseded by [ADR-0020](0020-kraken-archive-for-backtest-history.md) — 2026-10-14.
Originally accepted 2026-09-09.

## Context and problem statement

`docs/research/03-baseline-backtest.md` (work package 2C) documented a
hard limit: Kraken's public API does not serve historic OHLCV klines at
all — its OHLC endpoint always returns only its own rolling window of the
most recent candles (confirmed empirically: ~720 candles regardless of
the `since` timestamp requested), and Freqtrade itself knows this
(`exchange.get_option("ohlcv_has_history")` is `False` for Kraken). The
documented workaround, `--dl-trades` (rebuild OHLCV from raw trade
history), was benchmarked against this repo's actual pairs and found
infeasible: on the order of two hours for 30 days of BTC/USD trades alone,
days for a full multi-year/6-pair pull.

The practical result was a 4h backtest covering only ~4 months — nowhere
near enough to claim coverage of even one full market regime (Gate 1,
`docs/08-paper-exit-criteria.md`), and the review of that run flagged it.
We need multi-year 4h history for the 6 whitelisted pairs, without a paid
data provider (explicitly deferred to "Phase 5 if ever",
`docs/phase-2-plan.md` §1), and without an exchange API key.

## Decision drivers

- Gate 1 needs backtest history long enough to plausibly span more than
  one market regime; Kraken's public API cannot supply it under any
  method tested.
- No paid data provider (phase-2-plan.md §1 decision, unchanged).
- No exchange API key required for Phase 2 (dry-run only; ADR-0002 key
  creation is still gated on Kraken residency).
- Must not change which exchange the system trades on — Kraken remains
  the sole execution venue (ADR-0001, ADR-0002, ADR-0003's "LLM/backtest
  never places orders" boundary is unaffected either way).

## Considered options

- **Binance public API for backtest OHLCV only, Kraken unchanged for
  execution**
- Continue backtesting on Kraken's ~4-month window only
- Run Kraken's `--dl-trades` unattended for multiple days to reconstruct
  longer history
- A paid historical-data provider

## Decision outcome

Chosen option: **Binance, via `ccxt`, public endpoints only, for backtest
OHLCV history only.** Kraken remains the sole exchange in
`config.dry_run.json` (`exchange.name: kraken`) and the sole execution
venue for dry-run/live — this ADR does not touch order routing, key
scoping, or ADR-0001/0002/0003 in any way. `scripts/fetch_ohlcv.py` (the
renamed, `--venue`-flagged successor to `scripts/fetch_kraken_ohlcv.py`)
pulls from whichever venue is requested; `make backtest`-style runs that
use Binance-sourced history point Freqtrade's `--datadir` at
`user_data/data/binance/` and pass `--pairs` explicitly (see "Pair
mapping" below) — `config.dry_run.json` itself is untouched.

### Pair mapping and liquidity check

Binance's own `BTC/USD`-style markets exist but are effectively
illiquid — checked live: `BTC/USD` quote volume ≈ $796K/day vs. `BTC/USDT`
≈ $1.09B/day, roughly **1,370× more liquid**. The whitelisted pairs are
therefore pulled from Binance as their `USDT` equivalents (`BTC/USDT`,
`ETH/USDT`, `SOL/USDT`, `XRP/USDT`, `LINK/USDT`, `LTC/USDT`), not literal
`USD` pairs. Unlike Kraken, Binance's OHLC endpoint supports genuine
historical pagination via `since` — verified live, a two-year-old `since`
on the 4h timeframe returns real candles starting near that date, not a
rolling-window truncation.

### Price-divergence caveat — and why it's acceptable here

This backtest run is **not** a claim about what P&L this strategy would
have produced trading on Kraken. Two real divergences are introduced:

1. **Cross-venue price divergence.** Binance and Kraken are different
   order books; prices track each other closely for large-cap pairs
   (arbitrage keeps majors tightly coupled across liquid venues) but are
   not identical tick-for-tick, and diverge more for lower-liquidity
   pairs (e.g. LINK, LTC) than for BTC/ETH.
2. **Quote-asset divergence.** `USDT` is a USD-pegged stablecoin, not USD
   itself. It has historically traded within a tight band of $1 (typically
   low basis points) with rare de-peg stress episodes, but it is not
   contractually equivalent to USD.

**Why this is acceptable for this purpose:** `Baseline4h` is an EMA(20)/
EMA(50) cross strategy — its entries and exits are driven by multi-percent
trend moves, not sub-1% price precision. A cross-venue basis difference or
a stablecoin depeg of a few basis points does not plausibly flip an EMA
crossover or materially move a 2×ATR stop distance. This run's purpose is
**signal validation** — does the entry/exit logic behave sensibly over a
period long enough to contain more than one regime — not **execution
validation**, which is what work package 2D's Kraken dry-run against real
Kraken market data is for, and which this ADR does not change or weaken.
Any result from Binance-sourced backtesting is reported as directional
evidence about the strategy's logic, never as a promotable P&L number in
its own right — Gate 1/Gate 2 promotion still requires the walk-forward
and paper stages this ADR does not touch.

### Consequences

**Good:**
- Unblocks multi-year 4h backtesting with no paid provider, no API key,
  and no multi-day unattended download.
- Kraken stays the sole execution venue; no change to ADR-0001/0002/0003,
  key scoping, or any live/dry-run code path.

**Bad / accepted trade-offs:**
- Binance-sourced backtest results are not a precise forecast of Kraken
  economics (fees, slippage, exact fills differ by venue) — reported
  explicitly as such wherever these results are used.
- Adds a second data venue to reason about; `scripts/fetch_ohlcv.py`'s
  `--venue` flag and per-venue datadir (`user_data/data/kraken/` vs.
  `user_data/data/binance/`) keep the two explicitly separate rather than
  silently mixed.
- `USD` vs. `USDT` pair naming is a real seam: any future code that
  assumes Freqtrade's `pair_whitelist` (Kraken `USD` pairs) also names the
  backtest data files must account for the `USDT` substitution — this is
  handled by explicit `--pairs` overrides at the CLI, not a silent
  filename rewrite.

## More information

This ADR is scoped to backtest data sourcing only. It does not change
`docs/04-architecture/execution-freqtrade.md`, `config.dry_run.json`'s
`exchange.name`, or any requirement in `docs/02-requirements.md`. If a
future phase wants Binance-equivalent fee/slippage assumptions modeled
explicitly (rather than reusing the Kraken-taker-fee-based assumption in
`docs/research/03-baseline-backtest.md`), that is a separate decision, not
implied by this one.
