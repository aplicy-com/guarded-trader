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

Instead, `scripts/fetch_ohlcv.py --venue kraken` (new, this work package) pulls
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
   (a) letting `scripts/fetch_ohlcv.py`'s underlying trades-based
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

## Re-run on 2-year Binance data

Follow-up from the 2C review: per
[`ADR-0010`](../05-adr/0010-binance-ohlcv-for-backtest-history.md),
backtest OHLCV history can be sourced from Binance (multi-year 4h
available via public API, no key) while Kraken remains the sole execution
venue. This section re-runs the exact same `Baseline4h` strategy —
**no strategy code changed, no parameters touched** — against 2 years of
real Binance 4h history, to see whether the short-window result above
holds up on a real sample.

**Read the price-divergence caveat in ADR-0010 before treating this as a
Kraken-equivalent result:** the pairs below are Binance's `USDT` markets
(`BTC/USD` etc. exist on Binance but are ~1,370× less liquid than their
`USDT` equivalents — checked live), not literal Kraken `USD` pairs. This
is signal-validation evidence about the strategy's logic over a long
window, not a forecast of Kraken-specific P&L.

### Data

```
docker compose -f infra/docker-compose.yml run --rm -v "$(pwd)":/repo --entrypoint python freqtrade \
  /repo/scripts/fetch_ohlcv.py --venue binance --timeframes 4h --days 730
```

All 6 pairs returned the full requested window — Binance's OHLC endpoint
honours `since` for genuine historical pagination, unlike Kraken's:

| Pair | Candles | Coverage |
|---|---|---|
| BTC/USDT, XRP/USDT, ETH/USDT, SOL/USDT, LINK/USDT, LTC/USDT | 4,380 each | 2024-09-09 → 2026-09-09 (729.8 days, ~2 years) |

### Backtest configuration

```
docker compose -f infra/docker-compose.yml run --rm freqtrade backtesting \
  --config user_data/config.dry_run.json \
  --config user_data/config.backtest-binance.json \
  --strategy Baseline4h \
  --datadir user_data/data/binance \
  --pairs BTC/USDT XRP/USDT ETH/USDT SOL/USDT LINK/USDT LTC/USDT \
  --fee 0.0036 \
  --enable-protections \
  --breakdown day
```

`config.dry_run.json` is **unchanged** — Freqtrade's `StaticPairList`
rejects `USDT`-quoted pairs against a `USD` `stake_currency`, so a small
overlay file, `services/freqtrade/user_data/config.backtest-binance.json`
(new, this change — `{"stake_currency": "USDT"}` and nothing else), is
merged on top via a second `--config`. It exists only for this backtest
variant and is never used for dry-run/live. Same 0.36% fee assumption
(0.26% Kraken taker + 0.10% slippage buffer — kept as-is; see ADR-0010's
"More information" on why a Binance-specific fee model is a separate,
not-yet-made decision), same `--enable-protections`, same `$100`/3-slot
sizing.

### Results

#### Total

| Metric | Value |
|---|---|
| Backtest window | 2024-09-19 20:00 → 2026-09-09 16:00 UTC (~720 days, ~2 years — after 60-candle warmup) |
| Trades | 168 (36 win / 132 loss / 0 draw, 21.4% win rate) |
| Starting → final balance | 100.00 → 97.19 USDT |
| Total profit | −2.811 USDT (−2.81%) |
| Total trade volume | 14,460.10 USDT |
| Total fees paid | ≈ 51.87 USDT (computed the same way as the original run) |
| **Fee ratio (fees / gross winning P&L)** | **19.8%** (51.87 / 261.54) |
| Sharpe (closed trades) | **−0.01** |
| Sharpe (daily wallet balance) | **0.19** |
| Sortino (closed trades) / (daily wallet) | −0.06 / 0.27 |
| Calmar (closed trades) / (daily wallet) | −0.11 / −0.08 |
| Max drawdown (closed-trade basis) | **65.73%** (143.76 USDT) |
| Max drawdown (daily wallet basis) | **71.60%** (188.73 USDT) |
| Market change (buy & hold, equal-weight) over window | 21.96% |
| CAGR (annualised) | −1.44% — meaningful this time (real ~2-year window, not a short-window extrapolation) |
| Rejected entry signals | 78 |

Unlike the short-window run, **both** Sharpe bases agree here — trade-based
and daily-wallet-based are both far below the Gate 1 floor of 1.0 (one is
even negative). The ambiguity flagged in the short-window assessment
didn't matter this time; a longer sample resolved it in the negative
direction on both measures. The **65–72% max drawdown** is not a Gate 1
criterion by itself, but it is worth stating plainly: this is far beyond
anything that would survive Gate 2's future <10% drawdown threshold or
the live max-drawdown halt (R4 AC4.2, 10%) — this run would have tripped
that halt many times over.

#### Per pair

| Pair | Trades | Win% | Total profit (USDT) | Total profit % |
|---|---|---|---|---|
| XRP/USDT | 29 | 20.7% | 89.32 | 89.32% |
| BTC/USDT | 33 | 30.3% | 8.37 | 8.37% |
| SOL/USDT | 25 | 32.0% | −2.68 | −2.68% |
| ETH/USDT | 25 | 20.0% | −25.16 | −25.16% |
| LINK/USDT | 22 | 9.1% | −27.37 | −27.37% |
| LTC/USDT | 34 | 14.7% | −45.30 | −45.30% |
| **Total** | **168** | **21.4%** | **−2.81** | **−2.81%** |

Every pair produced trades this time (unlike the short window, where
LINK/USD had zero) — a longer window gives the EMA cross far more
opportunities to fire, in both directions.

#### Exit reasons

| Exit reason | Count | Avg profit % | Total profit (USDT) |
|---|---|---|---|
| `exit_signal` (EMA cross-down) | 62 | +8.79% | +200.50 |
| `trailing_stop_loss` (fixed ATR stop, same caveat as before — not an actual trailing stop) | 103 | −4.57% | −219.23 |
| `force_exit` (open at data end) | 3 | +21.10% | +15.92 |

The pattern is consistent with the strategy's design intent — winners
(`exit_signal`) average a much larger gain than losers (`trailing_stop_loss`,
which caps loss size by construction) — but losers happen roughly 1.7× as
often (103 vs. 62), and net out to a small loss once fees are included.
This is a much more legible, and much less flattering, picture than the
short-window run's.

#### Single-trade / force-exit dominance

Net profit this run is close to zero (−2.81 USDT), which makes "% of net
profit" an unstable denominator (a near-zero denominator inflates any
ratio) — reported against both net and gross for that reason:

| | Amount (USDT) | % of net profit (unstable — see above) | % of gross winning P&L (261.54 USDT) |
|---|---|---|---|
| Largest single trade (XRP/USDT, `exit_signal`) | 106.78 | 3,798% | 40.8% |
| `force_exit` group (3 trades) | 15.92 | 566% | 6.1% |

The single largest trade alone accounts for 40.8% of all gross winning
P&L — a large concentration, though less extreme than the short-window
run's force-exit group (which was larger than the entire net profit
figure there). See the Gate 1 "no single-trade dominance" criterion added
to `docs/08-paper-exit-criteria.md` following this review.

### Assessment against Gate 1

**Fails, more clearly than the short-window run.** Tunable parameters
still pass (4 ≤ 6) and the fee/slippage assumption is unchanged and still
adequate, but:

- **In-sample Sharpe ≥ 1.0**: fails on both bases (−0.01 and 0.19), no
  ambiguity this time.
- **Walk-forward**: still not run — out of scope for this follow-up too.
- **Minimum backtest history**: this criterion is now satisfied in terms
  of raw duration (~2 years, spanning both an uptrend and the drawdown
  above) — but the strategy simply does not clear the Sharpe floor on
  this longer, more representative sample.
- **Single-trade dominance**: fails (40.8% of gross winning P&L from one
  trade) against the new criterion added below.

**Net: the short-window backtest's positive result does not hold up.**
This is exactly the outcome the Gate 1 minimum-history requirement exists
to catch — a 3.6-month sample showed a positive, borderline-Sharpe result
that a real ~2-year sample reverses. Nothing here suggests the original
run's numbers were wrong; it demonstrates why a short backtest window is
not sufficient evidence on its own, independent of any question about
this specific strategy's merit.

## Re-run at the verified Kraken Tier-1 fee (2026-10-14)

The evidence review (`docs/research/evidence-review-2026-10/01-evidence-review.md` §0) found the
0.26 % taker assumption above was wrong: Kraken's official fee schedule, re-checked on
2026-10-14, puts an account under $2,500 of 30-day volume at **Tier 1: 0.40 % maker / 0.80 %
taker**. Backtests now take their fee from one file,
`services/freqtrade/user_data/config.backtest-costs.json`: **0.009 per side** (0.80 % taker +
0.10 % slippage, every fill priced as taker; ADR-0021). Strategy code and parameters are
unchanged; nothing was tuned.

**A second change had to be controlled for.** Since the run above, `config.dry_run.json` went
from `max_open_trades: 3` to `2` (commit 89d82cc, risk settings for the live pilot). Running
today's config at the new fee therefore changes two things at once. The table separates them:
row A reproduces the original run exactly (same data, 3 slots, `--fee 0.0036`) and lands on the
original numbers to the cent, so rows B–E differ from it only in what they say.

Command shape (one-off; the API-server JWT is a throwaway random value because the run has no
`.env`; the server is disabled):

```
docker run --rm -v "$PWD/services/freqtrade/user_data:/freqtrade/user_data" \
  -e FREQTRADE__API_SERVER__ENABLED=false -e FREQTRADE__API_SERVER__JWT_SECRET_KEY=<random> \
  freqtradeorg/freqtrade:2026.8 backtesting --config user_data/config.dry_run.json \
  [--config user_data/config.backtest-binance.json --datadir user_data/data/binance \
   --pairs BTC/USDT XRP/USDT ETH/USDT SOL/USDT LINK/USDT LTC/USDT] \
  --config user_data/config.backtest-costs.json [--max-open-trades 3] \
  --strategy Baseline4h --enable-protections --export none --cache none
```

| Run | Data | Slots | Fee/side | Trades | Win % | Net profit | Sharpe (closed / daily wallet) | Max underwater | Market change |
|---|---|---|---|---|---|---|---|---|---|
| A. Original (reproduced) | Binance USDT, 2024-09-19 → 2026-09-09 | 3 | 0.36 % | 168 | 21.4 % | **−2.81 %** | −0.01 / 0.19 | 65.73 % | +21.96 % |
| B. **Fee only** | same | 3 | **0.90 %** | 168 | 16.7 % | **−45.94 %** | −0.14 / −0.45 | 79.87 % | +21.96 % |
| C. Today's config | same | 2 | 0.90 % | 117 | 16.2 % | −36.38 % | −0.06 / −0.16 | 81.85 % | +21.96 % |
| D. Kraken archive | Kraken USD (ADR-0020), 2024-09-09 → 2026-09-10 | 3 | 0.90 % | 176 | 15.9 % | −48.86 % | −0.17 / −0.50 | 79.28 % | +32.04 % |
| E. Kraken archive, today's config | same | 2 | 0.90 % | 121 | 16.5 % | −35.17 % | −0.06 / −0.14 | 80.70 % | +32.04 % |

**Reading it.** The fee alone (A → B) turns a roughly break-even two years into a loss of 46 % of
the account: the same 168 trades now pay ~$104 in fees instead of ~$52, and eight trades that
were small winners become losers (win rate 21.4 % → 16.7 %). The trade list is identical
(same entries, same exits); only the cost per trade moved. Two slots instead of three (B → C)
trades less and loses less, but is still deeply negative. Kraken's own candles (D, E) tell the
same story as Binance's within a few percentage points; the per-pair picture is the same too,
XRP the only pair with a large positive total, LTC/ETH/LINK the largest losers.

**Gate 1:** fails more clearly than before on every Sharpe basis. This is the expected outcome
and is reported plainly. The same strategy on the full canonical timerange (2022-01-01 →
2026-10-01) is the Baseline4h reference trial in `docs/research/05-first-candidates.md`.

## TBD

- Exact Gate 1 Sharpe calculation method (trade-based vs. daily-equity-
  based) — raised above, not previously specified in
  `docs/08-paper-exit-criteria.md`. TBD (Phase 3). (Moot for *this* run
  specifically, since both bases agree — but still unresolved as a
  general Gate 1 definition.)
- Minimum backtest history bar count/duration (`08-paper-exit-criteria.md`
  already carried this as TBD (Phase 3); this run sharpens it — whatever
  number is picked, Kraken's public API cannot supply more than ~120 days
  of 4h history without a multi-day trades pull, so Phase 3 planning
  needs to account for that explicitly). Binance-sourced history
  (ADR-0010) is one way to satisfy a longer-duration requirement for
  *signal validation* even though Kraken cannot supply it directly.
- Whether a Binance-specific fee/slippage assumption should replace the
  reused Kraken-taker-fee-based one for Binance-sourced backtests — not
  decided; see ADR-0010 "More information".
- Walk-forward validation (anchored and rolling) — still not run against
  this strategy on either data source.
