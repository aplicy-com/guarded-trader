# First candidates under the cost-consistent Gate 1: C05, C01, C04 vs the random-entry null

## Erratum (2026-11-01)

**The random-entry null below did not draw independent per-candle entries, as ADR-0021
specifies.** `research_harness.null.uniforms` turned candle timestamps into seconds with
`astype("int64") // 1e9`, which assumes nanosecond timestamps. Freqtrade 2026.8 (pandas 3) gives
millisecond dates. So every candle in a block of about 11.6 days got the same random draw: 27
distinct draws per 300 daily candles, and about 70 candles per draw on 4h.

The bug was found in research round 2 ([`08-round2-results.md`](08-round2-results.md),
"Erratum"). It was fixed in commit `11299cd`, with regression test
`test_null_uniforms_do_not_depend_on_datetime_resolution`.

**Re-scored 2026-11-01 without touching the registry:**
- Command: `HARNESS_STATE_RO=1 scripts/research-harness.sh run <Strategy> --recompute`.
- The registry is mounted read-only and opened in SQLite read-only mode.
- The run refuses unless each trial's recorded Sharpe, trade count and full daily-return series
  are reproduced exactly. All four were.
- Only the null changed: walk-forward and every other Gate 1 check came out identical.
- 200 seeds, same calibration, same seeds. N is unchanged (26).

| Candidate (trial) | Candidate Sharpe | Null median / p95, old → new | Percentile, old → new | MDD vs null median, old → new | Top-trade share vs null median, old → new | Null passes, old → new |
|---|---|---|---|---|---|---|
| Baseline4h (`4536361ffa38`) | −0.22 | −0.80 / −0.10 → −0.68 / −0.23 | 92nd → **95th** (above p95) | 83.7 % vs 90.5 % ✅ → vs 87.3 % ✅ | 24.3 % vs 10.6 % ❌ → vs 12.1 % ❌ | ❌ → ❌ |
| C05 (`dab671223355`) | −0.14 | −0.41 / −0.04 → −0.28 / +0.09 | 86.5th → **70th** | 83.2 % vs 90.5 % ✅ → vs 86.5 % ✅ | 23.5 % vs 10.1 % ❌ → vs 13.7 % ❌ | ❌ → ❌ |
| C01 (`59f2a1b1e63f`) | −0.57 | −0.64 / −0.33 → −0.58 / −0.32 | 65.5th → **52nd** | 91.8 % vs 88.7 % ❌ → vs 87.8 % ❌ | 16.9 % vs 16.6 % ❌ → vs 17.3 % ✅ | ❌ → ❌ |
| C04 (`4b08ad68cc6a`) | −0.38 | −0.41 / −0.14 → −0.35 / −0.11 | 56th → **42.5th** | 38.0 % vs 37.9 % ❌ → vs 35.6 % ❌ | 9.5 % vs 9.6 % ✅ → vs 9.7 % ✅ | ❌ → ❌ |

**Did any verdict change? No.**
- The null verdict is unchanged for all four.
- **Gate 1 still fails for all four**, on IS Sharpe, OOS/IS and the single-trade rule, regardless
  of the null.

Two sub-checks moved:
- **Baseline4h's Sharpe** now clears the null's 95th percentile, by 0.013. It still fails on
  top-trade concentration.
- **C01's top-trade share** now passes. It still fails on drawdown.

The reading of the body text changes in degree, not direction:
- The EMA-cross entry: Baseline4h is a little stronger than reported. C05 is weaker, at the 70th
  percentile, not the 86.5th.
- The TSMOM entries (C01, C04) sit at the 42nd–52nd percentile, that is, no better than random
  entry, as the text says.

The body below is left as originally written.

**Not re-scored:** the two NDAX-fee trials of [`06-ndax-feasibility.md`](06-ndax-feasibility.md)
(`f2d85e2482d9`, `7d418e2c3ea6`, at 0.20 % + 0.10 %). Their null was affected in the same way.
The fee change they ran under was reverted (commit `3038b97`), so they cannot be reproduced
through `config.backtest-costs.json` as it stands. Re-scoring them would need that fee restored
in a reviewed commit first.

Old JSON reports predate a later metrics change. They lack `scale_downs`, and their
`avg_*_profit_pct` differ in the tenth decimal place because trade stake became the entry-fill
cost. Neither figure is a Gate 1 input.

Date: 2026-10-14 (runs finished 2026-10-15 02:41 UTC).
Gates: [`08-paper-exit-criteria.md`](../08-paper-exit-criteria.md) Gate 1 as amended by
[ADR-0021](../05-adr/0021-cost-consistent-gate-1-and-random-entry-null.md). Data:
[ADR-0020](../05-adr/0020-kraken-archive-for-backtest-history.md).
Pre-registration: `services/research/candidates.json`, committed (beaece1) before any registered
run. **No parameter was tuned.** Every number below is the first and only registered run of each
candidate.

## Bottom line

**Nothing passes Gate 1. Nothing beats its random-entry null. All four lose money over
2022-01-01 → 2026-10-01 at Kraken Tier-1 taker cost, and BTC buy-and-hold beat all of them.**

- **C05** (Baseline4h without the ATR stop) is a little better than Baseline4h on every
  measure, but both are still around −60 % with ~83 % drawdowns. Removing the stop did not create
  an edge. Before fees both are profitable; fees take all of it and more.
- **C01** (weekly TSMOM) is the worst result: −89 %. It loses money **even before fees**, and it
  trades far more often than pre-registered (223 trades, 10-day holds, invested 76 % of the time).
- **C04** (C01 with vol-scaled size) did what was pre-registered: max drawdown fell from 92 % to
  38 % and losses shrank from −89 % to −30 %, because positions were smaller. Its entry signal is
  still C01's, so it still loses money, and it does not beat its own null either.

Said plainly, per the evidence review's prediction: at 0.90 % per side, none of these signals is
strong enough to pay for itself.

## Setup

| Item | Value |
|---|---|
| Data | Kraken official OHLCVT archive, verified; `data_snapshot_id` 6f4979b22d6aaafe |
| Canonical timerange | 2022-01-01 → 2026-10-01 (1,733 days); indicator warm-up from data before the start |
| Pairs, slots, wallet | BTC, XRP, ETH, SOL (from 2021-06-17), LINK, LTC vs USD; `max_open_trades` 2; $100; protections on |
| Cost | 0.009 per side (0.80 % Tier-1 taker + 0.10 % slippage), every fill priced as taker; stress at 0.018 |
| Sharpe | Daily mark-to-market equity, annualised √365, force exits excluded |
| Walk-forward | Anchored and rolling, 12-month IS / 3-month OOS, 15 OOS windows each (2023-01 → 2026-09) |
| Null (C11) | 200 seeds per candidate; candidate's own exits, stop, sizing, fee, slots; entry rate calibrated to the candidate's trade count (null mean within 5–10 %); no random entry on a candle where the candidate's exit fires |
| Sandbox | `--network none`, read-only repo/data, no capabilities, no `.env`, Freqtrade 2026.8 |
| Correctness check | On every run the harness's order-by-order equity rebuild equals Freqtrade's own final balance (difference < $1e-7). A second, unregistered C04 run reproduced every gated figure, all 200 null seeds and all 30 walk-forward windows bit for bit |
| Benchmark | BTC/USD buy-and-hold, no fees: **+75.0 %**, Sharpe **0.49**, max drawdown **67.0 %** |

## Results

| | Baseline4h (reference) | **C05** EMA flip, 4h | **C01** TSMOM 21d, 1d | **C04** C01 + vol sizing |
|---|---|---|---|---|
| Trial id | 4536361ffa38 | dab671223355 | 59f2a1b1e63f | 4b08ad68cc6a |
| Trades (own exits) / force exits | 272 / 2 | 240 / 2 | 223 / 2 | 236 / 2 |
| Net profit ($100 start) | **−$65.47** | **−$61.48** | **−$88.63** | **−$29.84** |
| CAGR | −20.1 % | −18.2 % | −36.7 % | −7.2 % |
| Daily-equity Sharpe | −0.22 | −0.14 | −0.57 | −0.38 |
| Max drawdown | 83.7 % | 83.2 % | 91.8 % | **38.0 %** |
| Win rate | 19.5 % | 22.9 % | 24.7 % | 25.0 % |
| Avg hold | 6.8 d | 8.6 d | 9.9 d | 9.5 d |
| Time invested | 69 % | 74 % | 76 % | 76 % |
| Fees paid | $167.50 | $152.09 | $58.85 | $55.39 |
| Net + fees ("gross", not compounded) | +$102.03 | +$90.61 | **−$29.78** | +$25.55 |
| Fee ratio (fees ÷ gross winning P&L) | 45.9 % | **39.6 %** | 47.3 % | 47.1 % |
| Exits | 164 ATR stop, 108 signal | 238 signal, 2 catastrophe stop | 214 signal, 9 catastrophe stop | 229 signal, 7 catastrophe stop, 24 scale-downs |
| Largest trade ÷ gross winning P&L | 24.3 % | 23.5 % | 16.9 % | 9.5 % |
| At 2× fee: net / Sharpe / MDD | −$93.55 / −0.95 / 95.2 % | −$94.12 / −0.94 / 94.7 % | −$92.17 / −0.81 / 93.7 % | −$60.30 / −1.08 / 64.1 % |

"Gross" adds back fees to net profit. It is path-dependent (after losses, stakes are smaller),
so it shows the sign of the pre-fee result, not what a zero-fee run would have returned.

### Walk-forward

All four have negative IS Sharpe, so the OOS ≥ 50 % of IS ratio is not defined and the criterion
fails at the IS floor. OOS windows are identical in both schemes (only the IS window differs).

| | Anchored IS mean / pooled OOS | Rolling IS mean / pooled OOS | OOS windows with Sharpe > 0 | Trades per OOS window |
|---|---|---|---|---|
| Baseline4h | −0.22 / −0.22 | −0.15 / −0.22 | 6 / 15 | 7–21 |
| C05 | −0.12 / −0.16 | −0.11 / −0.16 | 6 / 15 | 7–18 |
| C01 | −0.81 / −0.87 | −0.83 / −0.87 | 6 / 15 | 6–19 |
| C04 | −0.62 / −0.54 | −0.44 / −0.54 | 5 / 15 | 6–19 |

No candidate shows a stable edge that then decays out of sample; they are negative throughout.

### Against the random-entry null (C11)

The gate needs all three: Sharpe above the null's 95th percentile, drawdown below the null
median, top-trade share not above the null median.

| | Candidate Sharpe | Null Sharpe median / p95 | Candidate's percentile | Candidate MDD vs null median | Top-trade share vs null median | Passes |
|---|---|---|---|---|---|---|
| Baseline4h | −0.22 | −0.80 / −0.10 | 92nd | 83.7 % vs 90.5 % ✅ | 24.3 % vs 10.6 % ❌ | ❌ |
| C05 | −0.14 | −0.41 / −0.05 | 86.5th | 83.2 % vs 90.5 % ✅ | 23.5 % vs 10.1 % ❌ | ❌ |
| C01 | −0.57 | −0.64 / −0.33 | 65.5th | 91.8 % vs 88.7 % ❌ | 16.9 % vs 16.6 % ❌ | ❌ |
| C04 | −0.38 | −0.41 / −0.14 | 56th | 38.0 % vs 37.9 % ❌ | 9.5 % vs 9.6 % ✅ | ❌ |

- The **EMA-cross entry** (Baseline4h, C05) is better than random entries with the same exit —
  86th–92nd percentile, lower drawdown — but not at the 95th percentile, and its profits are more
  concentrated in a few trades than random entries' are. Something is there; at these costs it is
  not enough to make money and not strong enough to pass.
- The **TSMOM entry** (C01, C04) is indistinguishable from random entry with the same exit:
  56th–66th percentile, drawdowns equal to the null's median. C04's drawdown reduction comes from
  sizing, and random entries with the same sizing get the same reduction.

### Deflated Sharpe (reported, not gated)

Against the registry's N = 4 trials and cross-trial per-day Sharpe dispersion 0.0100, the
expected best-of-noise per-day Sharpe is 0.0106 (≈ 0.20 annualised). DSR: Baseline4h 0.18,
C05 0.23, C01 0.05, C04 0.10. Probability that the true Sharpe is above zero (PSR vs 0): 0.32,
0.38, 0.11, 0.20. Minimum track record: infinite for all four, because every observed Sharpe is
below the benchmark. With four trials these numbers mainly confirm that nothing here is near a
pass; they become meaningful as N grows.

### Gate 1 scorecard

| Criterion | Baseline4h | C05 | C01 | C04 |
|---|---|---|---|---|
| ≤ 6 parameters | ✅ 4 | ✅ 3 | ✅ 4 | ✅ 6 |
| IS Sharpe ≥ 1.0 | ❌ | ❌ | ❌ | ❌ |
| ≥ 8 OOS windows, both schemes | ✅ 15 | ✅ 15 | ✅ 15 | ✅ 15 |
| Pooled OOS ≥ 50 % of IS | ❌ | ❌ | ❌ | ❌ |
| ≥ 100 trades over canonical | ✅ 272 | ✅ 240 | ✅ 223 | ✅ 236 |
| Fee ratio < 40 % | ❌ | ✅ | ❌ | ❌ |
| Single trade / force-exit group ≤ 30 % of net | ❌ (net < 0) | ❌ (net < 0) | ❌ (net < 0) | ❌ (net < 0) |
| Beats random-entry null | ❌ | ❌ | ❌ | ❌ |
| **Gate 1** | **Fail** | **Fail** | **Fail** | **Fail** |

## Against the pre-registered hypotheses

- **C05**: "Removing the ATR stop improves Sharpe and cuts losing trades; if unchanged, the cross
  has no edge. Predicted indistinguishable from its null and to fail the fee ratio on 4h."
  *Partly confirmed, partly not.* Removing the stop did improve Sharpe (−0.22 → −0.14), cut trade
  count (272 → 240) and fees, and raised the win rate, but not by enough to matter. It is
  *better* than its null (86.5th percentile) rather than indistinguishable, and it is the only one
  to pass the fee-ratio check (39.6 %), narrowly. The evidence review's "a change of trend is the
  best stop" holds in direction; the cross itself is the bigger problem.
- **C01**: "Positive after-cost Sharpe, beats its null; 60–120 trades per 3 years."
  *Rejected.* Negative before and after fees, indistinguishable from random entry, and ~140 trades
  per 3 years: the top-2 ranking rotates positions between correlated pairs more often than the
  single-asset literature implies. This matches the review's warning that the effect has weakened
  since 2021 and is not shown to survive 1.0–1.8 % round trips.
- **C04**: "Materially lower drawdown and equity volatility than C01, lower return; fails
  IS Sharpe ≥ 1.0." *Confirmed for drawdown* (92 % → 38 %; at 2× fee, 94 % → 64 %). Return was
  *less* negative, not lower, because C01's return was negative. Fails the Sharpe floor as
  predicted. Vol-of-vol was pre-registered as a metric but the harness does not yet compute it;
  that is a gap in this report.

## What this does and does not show

- It shows that, on Kraken's own candles at the fee a $100 account actually pays, these three
  pre-registered ideas and the existing baseline do not have an edge large enough to trade.
- It does not show the ideas are worthless at lower cost. The EMA cross is profitable before fees
  and beats random entry at the 86th–92nd percentile; a slower variant that trades far less
  (C05 "variant B", weekly evaluation, pre-registered in 02 but not run here) is the obvious next
  trial. That would be a **new registered trial**, not a re-run.
- It does not show anything about live fills: every fill was priced as taker plus 0.10 %.
- No leak check (`lookahead-analysis`) has been run on any of them yet (follow-up below). C01's
  cross-pair ranking is the one that most needs it; since C01 lost money, a leak would have made
  it look better, not worse.
- The trial registry now holds N = 4. Every further idea tried adds to it.

## Follow-up list (not done in this change)

From `evidence-review-2026-10/04-validation-upgrades.md`, in its priority order. None of these
is implemented here; each needs its own plan.

| Priority | Item | Why it matters next | Review § |
|---|---|---|---|
| P0 (remaining) | `lookahead-analysis` / `recursive-analysis` wrapper, static leak lint, oracle quarantine | No candidate has been leak-checked. C01's cross-pair ranking reads other pairs' candles through the DataProvider and is the first thing to check | 12 |
| P0 (remaining) | Taker-only and 0.25 %/side slippage stress variants | Only the 2× fee stress is run; the base case already prices everything as taker | 11 |
| P1 | Harvey–Liu haircut Sharpe (BHY) | Second deflation view alongside DSR | 2 |
| P1 | PBO via CSCV over the whole registry | Needs ≥ ~30 trials before it says anything; report "insufficient trials" until then | 3 |
| P1 | Block-bootstrap drawdown distribution + top-3-removed P&L | Tests the live hard-loss limit against a distribution, not one observed MDD | 7 |
| P1 | Parameter plateau / stability score | Only meaningful once parameters are searched; none were here | 10 |
| P1 | `--timeframe-detail` on finalists | Intra-candle fill ordering for 4h candidates with stops | 13 |
| P1 | Paper fill-rate / slippage / consistency logger | Gate 2 now treats 20 trades as the fill-rate sample; something has to measure it | 13 |
| P1 | DSR threshold and per-OOS-window trade minimum | Both TBD (Phase 3) in `08-paper-exit-criteria.md` | 2, 6 |
| P1 | Vol-of-vol and per-year breakdown in the harness report | Pre-registered for C04, not computed | — |
| P2 | SPA / StepM over the registry | Family-wise check | 4 |
| P2 | Rolling-Sharpe / CUSUM / `ruptures` decay monitor | Before any live promotion | 14 |
| P2 | Bar-permutation test | Finalist diagnostic | 8 |
| P3 | CPCV with purge/embargo | Finalists only | 5 |

Operational follow-ups found while doing this work:

- **Back up the trial registry.** `services/research/state/registry.sqlite` is git-ignored and
  lives only on this Mac. Losing it resets N. It should go into the existing B2 backup, or its
  trial rows (without return series) should be exported to the repo after every run.
- **Ask Kraken about the archive's licence** (ADR-0020: none stated).
- **Verify the fee tier on the live account** (an order ticket), as the review asked. Everything
  here assumes Tier 1.
- `Baseline4h` is the strategy the ADR-0019 live pilot runs. ADR-0019 already treats it as a
  no-edge plumbing test; this result is consistent with that. Nothing in this change touches the
  pilot.

## Reproducing

```
make kraken-data                                   # data, verified (ADR-0020)
make research-run STRATEGY=C05EmaFlip4h            # refused now: already registered and scored
scripts/research-harness.sh run C05EmaFlip4h --no-register --out /out/check   # same numbers, no trial
scripts/research-harness.sh registry               # all trials, DSR against current N
```
