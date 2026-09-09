# Baseline4h backtest — work package 2C

Purpose: validate the execution path (data → indicators → signal → order →
ledger) end-to-end with one hand-written, non-tuned strategy. **This is
not an attempt to produce a promotable strategy**, and the result below
should be read that way — see the Gate 1 assessment at the end, which
this document reports plainly even though it does not pass.

Per instruction, parameters were **not tuned to improve this result**.
The numbers below are from the first backtest run against the values in
`Baseline4h.py`'s docstring (20/50 EMA cross, 14-period ATR, 2× ATR stop —
textbook defaults chosen before running the backtest, not fit to it).

## Data — actual coverage, and why it is short of "2 years"

`make download-data` (Freqtrade's normal OHLCV download) **fails outright
for Kraken**: Freqtrade knows Kraken's public OHLC endpoint does not serve
historic klines (`exchange.get_option("ohlcv_has_history")` is `False` for
Kraken) and refuses to run, directing you to `--dl-trades` (rebuild OHLCV
from raw trade history) instead.

`--dl-trades` was benchmarked against this repo's actual pairs before
committing to it: a plain `fetch_trades` call against live BTC/USD volume
measured ~1,000 trades per ~2.4s (Kraken's own rate limiting, not a local
bottleneck). Extrapolated, 30 days of BTC/USD trade history alone is on
the order of two hours; a full 730-day pull across all 6 whitelisted
pairs is on the order of days. That is not a background job to leave
running unattended for this work package.

Instead, `scripts/fetch_kraken_ohlcv.py` (new, this work package) pulls
directly via `ccxt.kraken().fetch_ohlcv()` and writes through Freqtrade's
own `IDataHandler.ohlcv_store`, so the on-disk format is exactly what
`freqtrade backtesting` expects — no synthetic or interpolated data, no
paid provider (consistent with `docs/phase-2-plan.md` §1). The result
confirms the same server-side limit from a different angle: Kraken's OHLC
endpoint returns only its own rolling window of the most recent ~720
candles, **regardless of the `since` timestamp requested** — a `since` of
two years ago on the 4h timeframe still comes back with only the trailing
~720 bars.

| Timeframe | Candles | Actual coverage | Requested |
|---|---|---|---|
| `1d` | 720 | 2024-09-19 → 2026-09-08 (~719 days, ~2 years) | 730 days |
| `4h` | 720 | 2026-05-12 → 2026-09-09 (~120 days, ~4 months) | 730 days |

Both timeframes hit the same ~720-candle Kraken-side cap; 4h's shorter
candle duration just means far less wall-clock history fits in that cap.
**1d effectively got the requested 2 years. 4h — the strategy's actual
timeframe — did not, by a wide margin**, and this is a hard external
constraint (confirmed directly against Kraken's API), not a scope
decision made for convenience. This is the single biggest caveat on
everything below, and it is the main reason this backtest does not clear
Gate 1 (see the assessment at the end). 1d data was downloaded per this
work package's instructions but is not used by `Baseline4h` (single
4h-timeframe strategy, no informative pairs) — it is available for a
future 1d-confirmation variant per `docs/phase-2-plan.md` §1.

## Strategy

`services/freqtrade/user_data/strategies/Baseline4h.py` — long-only,
single-timeframe EMA(20)/EMA(50) cross entry and exit, with a fixed
(non-trailing) ATR(14) × 2.0 stop set once at entry. Full logic and
parameter rationale are in the strategy's module docstring. 4 tunable
parameters (`ema_fast_period`, `ema_slow_period`, `atr_period`,
`atr_multiplier`), within the NFR5 ≤6 cap. The existing protections block
(`CooldownPeriod`, `StoplossGuard`, `MaxDrawdown`) was kept unchanged.

## Backtest configuration

```
docker compose -f infra/docker-compose.yml run --rm freqtrade backtesting \
  --config user_data/config.dry_run.json \
  --strategy Baseline4h \
  --fee 0.0036 \
  --enable-protections \
  --breakdown day
```

- **Fee: 0.36%**, applied on both entry and exit (Freqtrade's `--fee`
  semantics) — 0.26% Kraken taker fee (confirmed live in
  `docs/research/02-kraken-market-facts.md`) + 0.10% slippage buffer.
  Freqtrade's backtesting engine has no separate slippage model; its own
  config schema documents the `fee` field as the sanctioned way to
  simulate slippage in backtesting, which is the approach used here.
- `--enable-protections` — without this flag Freqtrade ignores a
  strategy's `protections` block during backtesting entirely, which would
  silently misrepresent how the strategy behaves live/dry-run.
- Backtest window (after 60-candle startup warmup for `EMA(50)`):
  2026-05-22 16:00 → 2026-09-09 12:00 UTC (~110 days).
- `dry_run_wallet` / stake sizing from `config.dry_run.json` unchanged
  ($100 starting balance, `max_open_trades: 3`, `unlimited` stake →
  ~$30-33/position, matching the sizing basis in
  `docs/research/02-kraken-market-facts.md`).

## Results

### Total

| Metric | Value |
|---|---|
| Trades | 22 (6 win / 16 loss / 0 draw, 27.3% win rate) |
| Starting → final balance | $100.00 → $118.44 |
| Total profit | $18.435 (18.44%) |
| Total trade volume | $1,405.26 |
| Total fees paid | ≈ $5.04 (computed from per-trade `fee_open`/`fee_close` × notional) |
| **Fee ratio (fees / gross winning P&L)** | **14.6%** ($5.04 / $34.50 gross winning P&L before fees) |
| Sharpe (closed trades) | **0.97** |
| Sharpe (daily wallet balance) | **1.81** |
| Sortino (closed trades) / (daily wallet) | 12.89 / 3.28 |
| Calmar (closed trades) / (daily wallet) | 34.97 / 27.79 |
| Max drawdown (closed-trade basis) | 9.24% ($9.24) |
| Max drawdown (daily wallet basis) | 12.10% ($12.47) |
| Market change (buy & hold, equal-weight) over window | 13.50% |
| CAGR (annualised) | 76.22% — **do not treat this as a real annual expectation**; it is a ~110-day result algebraically extrapolated to a year, which is exactly the kind of number NFR5/Gate 1 exist to prevent taking seriously |
| Rejected entry signals | 12 (protections/`max_open_trades` were active during the run) |

Freqtrade reports two Sharpe figures from different bases (trade-return
distribution vs. daily equity curve) and `docs/08-paper-exit-criteria.md`
does not specify which one Gate 1's "IS Sharpe ≥ 1.0" refers to — that
ambiguity is itself a real gap, noted in the TBD section below. The more
conservative of the two (0.97, closed trades) is used for the Gate 1 call
so as not to pick the number that happens to pass.

### Per pair

| Pair | Trades | Win% | Total profit | Total profit % |
|---|---|---|---|---|
| SOL/USD | 4 | 50.0% | $11.20 | 11.20% |
| XRP/USD | 4 | 25.0% | $4.92 | 4.92% |
| BTC/USD | 4 | 25.0% | $4.39 | 4.39% |
| ETH/USD | 4 | 25.0% | $0.11 | 0.11% |
| LINK/USD | 0 | — | $0.00 | 0.00% |
| LTC/USD | 6 | 16.7% | −$2.18 | −2.18% |
| **Total** | **22** | **27.3%** | **$18.44** | **18.44%** |

LINK/USD produced zero EMA-cross signals in the available ~110-day
window — not an error, just no qualifying trend on this pair/timeframe in
this short window.

### Exit reasons

| Exit reason | Count | Avg profit % | Total profit |
|---|---|---|---|
| `exit_signal` (EMA cross-down) | 5 | +7.89% | $11.94 |
| `trailing_stop_loss` (**this is the fixed ATR stop, not a trailing stop** — Freqtrade's exit-reason taxonomy labels every `custom_stoploss` exit `trailing_stop_loss` regardless of whether the stop actually trails; `Baseline4h`'s stop is fixed at entry, see the strategy docstring) | 14 | −3.04% | −$13.52 |
| `force_exit` (position still open at end of backtest data, closed by the backtest engine, not the strategy) | 3 | +21.92% | $20.01 |

The 3 `force_exit` trades — closed only because the data window ended,
not because of any signal — account for $20.01 of the $18.44 total net
profit. **Without them the strategy would have shown a net loss over this
window.** This is disclosed because it is exactly the kind of small-
sample distortion Gate 2's "backtest consistency over net P&L" philosophy
(`docs/08-paper-exit-criteria.md`) exists to guard against, and 22 trades
total is a small sample by any standard.

## Assessment against Gate 1 (`docs/08-paper-exit-criteria.md`)

**This strategy does not clear Gate 1 as run. Said plainly, per
instruction — this was expected: the point of this work package was to
validate the execution path, not to produce a promotable strategy.**

| Gate 1 criterion | Result |
|---|---|
| Tunable parameters ≤ 6 | ✅ Pass — 4 |
| Walk-forward, anchored **and** rolling, both run | ❌ **Not done.** Out of scope for this work package (backtest only); a strategy cannot be evaluated against the OOS/IS ratio test without it. This alone is sufficient to keep the strategy at Gate 1. |
| In-sample Sharpe ≥ 1.0 (absolute floor) | ⚠️ **Marginal / metric-dependent.** 0.97 on the closed-trade basis (just under), 1.81 on the daily-wallet basis (over). Using the more conservative figure: **fails** the strict floor, though not by much. |
| OOS Sharpe ≥ 50% of IS Sharpe | N/A — no walk-forward run |
| Backtest fee/slippage ≥ live taker fee + buffer | ✅ Pass — 0.36% used (0.26% taker + 0.10% buffer) vs. the confirmed 0.26% Kraken taker fee |
| Minimum backtest history — enough bars to cover ≥1 full market regime | ❌ **Fail.** ~110 usable days (~3.6 months) on the 4h timeframe is far short of "a full market regime" by any reasonable reading. This is a hard Kraken public-data-API limit (see Data section above), not a scope choice. |

**Net: not eligible to proceed to the paper stage.** Before this or any
successor strategy is re-evaluated against Gate 1 in earnest, three real
gaps need to be closed, none of which are Phase 2 work:

1. **Backtest history.** Kraken will not serve more than ~120 days of 4h
   history via its public API at all, by any method tested here short of
   a multi-day trades-reconstruction pull. Longer history requires either
   (a) letting `scripts/fetch_kraken_ohlcv.py`'s underlying trades-based
   equivalent run unattended over days, (b) accumulating real history
   candle-by-candle simply by running dry-run over time (this is in fact
   what work package 2D does next), or (c) a paid data provider —
   explicitly deferred to "Phase 5 if ever" per `docs/phase-2-plan.md`
   §1. TBD (Phase 3) which of these the walk-forward step actually uses.
2. **Walk-forward validation** (anchored and rolling) has not been run
   against this strategy at all yet.
3. **Which Sharpe calculation Gate 1 means** (trade-based vs.
   daily-equity-based) is not specified in
   `docs/08-paper-exit-criteria.md` and produced materially different
   pass/fail answers here (0.97 vs. 1.81) — needs to be pinned down
   before Gate 1 is used as a real go/no-go gate, not just for this
   strategy.

## TBD

- Exact Gate 1 Sharpe calculation method (trade-based vs. daily-equity-
  based) — raised above, not previously specified in
  `docs/08-paper-exit-criteria.md`. TBD (Phase 3).
- Minimum backtest history bar count/duration (`08-paper-exit-criteria.md`
  already carried this as TBD (Phase 3); this run sharpens it — whatever
  number is picked, Kraken's public API cannot supply more than ~120 days
  of 4h history without a multi-day trades pull, so Phase 3 planning
  needs to account for that explicitly).
