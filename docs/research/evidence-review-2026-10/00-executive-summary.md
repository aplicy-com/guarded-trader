# Executive Summary: Fix the Fee, Size by Volatility, Count the Trials

Purpose: one-page decision summary of the evidence review for the Kraken spot, long-only, Freqtrade + nightly-LLM trading system. Grades, numbers and links are in files 01–05.
Date: 2026-10-14

## What the evidence says

The only crypto return effect with more than one after-cost study behind it is weekly-scale (7–28-day) time-series momentum on BTC and large caps, and two independent subperiod splits show it weakening after 2020–21; everything else tested is grade C for this system. Drawdown reduction comes from exposure — vol-scaled sizing and a long-flat regime filter — while stop and trailing-stop overlays on trend rules add nothing or hurt after 20 bp costs ("a change of trend is the best stop loss", grade B). Every public live test of autonomous LLM trading has a majority of losers, in-training-window LLM backtests are contaminated by memorisation, and the one leakage-safe, trial-counted audit certified 0 of ~200 LLM-proposed strategies. The IS Sharpe ≥ 1.0 gate has no power once a few hundred candidates are scored: the expected best-of-noise Sharpe is ≈ 1.7 at N = 300. Kraken's official Tier-1 fee page, fetched on the research date, shows 0.40% maker / 0.80% taker, not the assumed 0.16/0.26 — verify this first.

## The three highest-value changes

1. **Verify the fee tier in the live account and re-run every gate at the true fee**, with `--fee` set explicitly and stop exits modelled as taker. At 0.40/0.80 a round trip costs 0.8–1.6% before slippage and the fee-ratio gate needs 2–4% average gross profit per trade. The ≥ 20-trades-in-8-weeks gate implies a ~2.8-day hold no cost-aware evidence supports; move the statistical trade count to the 3-year backtest and keep 20 trades as the paper-phase fill-rate sample.
2. **Make exposure the primary risk lever, not cleverer stops:** vol-scaled sizing capped at 1× plus a slow long-flat regime filter, judged on drawdown and vol-of-vol. The 65–72% drawdown came from full-size positions in a 70–80%-vol asset; the fixed ATR stop was a cost, not a protection.
3. **Add a pre-registered trial registry and gate on Deflated Sharpe, PBO over the whole registry, and a random-entry-same-exit null**, plus cost stress ×2, parameter plateau and the Freqtrade leak analyses on every candidate. Without the registry nothing knows how many times the loop has tried.

## The three candidates to test first

- **C01** — weekly-scale TSMOM, long-flat, trend-flip exit, daily bars: the only entry effect with replicated after-cost support; expected to fail the trade-count gate, which is informative about the gate.
- **C04** — vol-scaled exposure overlay (≤ 1×) on C01: the evidence's drawdown lever; untested in capped form, so pre-register MDD and vol-of-vol as the metrics.
- **C05** — the existing EMA(20/50) cross with the 2×ATR stop removed: a one-variable A/B against the only known result; if nothing changes, the cross has no edge and "exits matter most" is falsified cheaply.

Run the random-entry null (C11) against each before reading any gate.

## Data and licensing action

Kraken now publishes a free official bulk OHLCVT archive (every pair through 30 June 2026, 240-minute bars, quarterly updates, no licence stated), removing the 720-candle reason for backtesting on Binance. Binance Vision's terms (26 Aug 2026) are CC BY-NC-SA, ban "live proprietary trading execution" and claim derived models. Revisit ADR-0010: Kraken-native data for the promotion path, Binance as a private validation feed only, no data committed to the repo.

## What we don't know

- Whether the 0.40/0.80 tier applies to this Canadian account, and since when.
- Any after-cost, out-of-sample result for TSMOM or any stop design on 4h spot bars.
- The drawdown of a ≤ 1× vol-targeted long-only BTC position with costs.
- LINK and LTC correlations with BTC (SOL 0.75, XRP 0.55 known); any bear-market matrix.
- Kraken maker fill rates, small-order slippage, and the per-pair minimum fee.
- Any crypto strategy half-life; any DSR/PBO threshold calibrated for a solo nightly loop.
- Whether Binance Vision terms cover the REST API; the licence of Kraken's archive.

No source supports a claim that this system will be profitable; the base rate for a small retail systematic bot being net profitable after fees over 12 months is low single digits.
