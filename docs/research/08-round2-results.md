# Research round 2 — results: four low-turnover candidates at real Kraken cost

**Run 2026-11-01** under the pre-registration frozen in
[`07-round2-preregistration.md`](07-round2-preregistration.md) (spec commit `66d1ce6`; engine
commit `e7790f2`; null fix `11299cd`). Data snapshot `6f4979b22d6aaafe`. 20 trials, 200 seeds per null.
Trial registry N = **26** (6 from round 1 + 20 here). Machine-readable summary:
[`round2-evidence/results-summary-2026-11-01.json`](round2-evidence/results-summary-2026-11-01.json).

## Bottom line

**No candidate passes Gate 1, and no candidate passes round 2.** Trigger 2 ("a candidate passes
Gate 1 at real costs") is still unmet.

- **All four fail Gate 1 on the ≥ 100-trade minimum**, as known before running: each closed 0–4
  trades in 4.75 years. They also all fail IS Sharpe ≥ 1.0 (best 0.85), the walk-forward
  OOS/IS test, and the 30 % single-trade rule. None of those failures is close to the line.
- **The economics are better than anything in round 1, and they are real at Tier-1 cost:**
  - R2-01 (200-day trend filter) and R2-04 (trend × vol target) roughly tripled the account
    on 2022–2026 (+200 % / +199 %) with a 27 % max drawdown.
  - BTC buy-and-hold made +78 % with a 67 % drawdown.
  - Fees were only 6–8 % of gross winning P&L for the three that closed trades. At ≤ 2 round trips a year, cost stops being the
    problem: doubling it to 1.80 % per fill costs R2-01 about 26 points of a 200 % return.
- **The timing is not shown to be skill.**
  - Against the matched switching null (same number of switches, same time in market, random
    timing), the four candidates sit at the 72nd–94th percentile, none above the 95th.
  - R2-01 and R2-04 do beat ADR-0021's C11 random-entry null (98th percentile, lower drawdown,
    less concentrated). Random *exit* timing with the same exposure does about as well.
  - Four or five trades are too few decisions to tell rule from luck. DSR (N = 26) is 0.26–0.35.
- **Only R2-01 and R2-02 can actually be traded at CA$35.** R2-03 and R2-04's drift rebalances
  include fills as small as US$3.61 and US$4.36, below Kraken's ~US$4.66 BTC minimum (US$5.59 with
  the pre-registered 120 % headroom).
- **Over 2015–2026 every candidate made less money than buying and holding BTC**, except R2-02 on
  its shorter 2016–2026 range. Each one did cut the worst drawdown (from 84 % to 53–81 %). The
  pre-registered prediction for R2-01, "its edge over buy-and-hold, if any, is drawdown, not
  return", held for the trend filters.

## Setup (as frozen)

| | |
|---|---|
| Engine | Daily long-or-flat portfolio engine (`research_harness.round2`). Decision at the check day's close, fill at next open, Freqtrade's spot fee model. It emits Freqtrade-shaped trade rows, so every Gate 1 figure below comes from the existing harness functions (`metrics.compute_metrics`, `walkforward`, `null.verdict`, `dsr`, `cli.gate1`), unchanged |
| Gate 1 basis | Canonical 2022-01-01 → 2026-10-01, 0.90 % per fill (Tier-1 taker 0.80 % + 0.10 % slippage). Force exits excluded from headline figures |
| Account view | The whole account marked daily, the final open position included and sold at the last close with costs. Used for the round-2 economics, the benchmark and the matched null |
| Start balance | CA$35 = US$25.01 (returns are scale-free; the balance only enters the minimum-order check) |
| Quote | USD (measured, 07 §6) |
| Sandbox | `scripts/research-round2.sh`: no network, read-only repo, no `.env`, no capabilities |

## Results

### T1. Headline, canonical base (2022-01-01 → 2026-09-30, 0.90 % per fill, account view)

| Candidate | Net return | CAGR | Max DD | Sharpe | Max round trips / yr | Closed trades (Gate 1) | Fills |
|---|---|---|---|---|---|---|---|
| R2-01 Trend filter | +200.1 % | +26.0 % | 27.2 % | 0.85 | 1.50 | 4 (+1 force exit) | 10 |
| R2-02 Dual momentum | +166.9 % | +23.0 % | 38.3 % | 0.73 | 1.49 | 4 (+0 force exit) | 8 |
| R2-03 Vol target | +123.7 % | +18.5 % | 59.8 % | 0.60 | 0.84 | 0 (+1 force exit) | 12 |
| R2-04 Trend × vol | +199.0 % | +25.9 % | 27.1 % | 0.88 | 1.49 | 4 (+1 force exit) | 13 |
| **BTC buy-and-hold** (0.90 % in and out) | +77.8 % | +12.9 % | 67.0 % | 0.48 | 0.5 | — | 2 |
| BTC buy-and-hold, fee-free (harness) | +75.0 % | — | 67.0 % | 0.49 | — | — | — |

### T2. Gate 1 (ADR-0021) checks, canonical base — `research_harness.cli.gate1`

| Check | R2-01 | R2-02 | R2-03 | R2-04 |
|---|---|---|---|---|
| ≤ 6 params | pass | pass | pass | pass |
| IS Sharpe ≥ 1.0 | **fail** | **fail** | **fail** | **fail** |
| WF ≥ 8 windows | pass | pass | pass | pass |
| WF OOS ≥ 50 % IS | **fail** | **fail** | **fail** | **fail** |
| ≥ 100 trades | **fail** | **fail** | **fail** | **fail** |
| Fee ratio < 40 % | pass | pass | **fail** | pass |
| Top trade ≤ 30 % net | **fail** | **fail** | **fail** | **fail** |
| Force exits ≤ 30 % net | pass | pass | **fail** | pass |
| Beats C11 null | pass | **fail** | **fail** | pass |
| **Gate 1** | **FAIL** | **FAIL** | **FAIL** | **FAIL** |

Values behind the checks:

| | R2-01 | R2-02 | R2-03 | R2-04 |
|---|---|---|---|---|
| Gate 1 Sharpe (force exits excluded) | 0.82 | 0.73 | 0.00 | 0.85 |
| Closed trades | 4 | 4 | 0 | 4 |
| Fee ratio | 7.3 % | 6.1 % | ∞ (no closed trade) | 7.5 % |
| Top trade / net | 59.9 % | 114.6 % | — (no closed trade) | 60.8 % |
| WF anchored: IS mean / pooled OOS | 0.63 / -1.25 | 0.20 / -1.12 | 0.00 / 0.00 | 0.66 / -1.25 |
| WF rolling: IS mean / pooled OOS | 0.16 / -1.25 | -0.19 / -1.12 | 0.00 / 0.00 | 0.16 / -1.25 |
| WF OOS trades per window (rolling) | 0,0,1,0,0,0,1,0,0,0,0,1,0,0,0 | 0,0,0,0,0,0,0,0,0,0,0,1,0,1,0 | 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0 | 0,0,1,0,0,0,1,0,0,0,0,1,0,0,0 |
| C11: Sharpe vs null p95 (pctile) | 0.82 vs 0.73 (98) | 0.73 vs 0.83 (50) | 0.00 vs 0.00 (0) | 0.85 vs 0.75 (98) |
| C11: MDD vs null median | 27.2 % vs 34.5 % | 38.3 % vs 32.8 % | 0.0 % vs 0.0 % | 27.1 % vs 33.2 % |
| C11: top share vs null median | 55.5 % vs 71.0 % | 97.5 % vs 97.5 % | — | 56.3 % vs 70.7 % |
| C11: null mean trades (cand.) | 4.2 (5) | 3.6 (4) | 1.0 (1) | 4.2 (5) |
| DSR (N = 26), reported | 0.32 | 0.26 | 0.01 | 0.35 |
| 2× cost (1.80 %) Gate 1 Sharpe | 0.78 | 0.69 | 0.00 | 0.80 |

### T3. Round-2 requirements, base trials

| | R2-01 | R2-02 | R2-03 | R2-04 |
|---|---|---|---|---|
| Matched null: Sharpe vs p95 (pctile) | 0.85 vs 1.09 (84) | 0.73 vs 0.78 (94) | 0.60 vs 0.66 (72) | 0.88 vs 1.07 (84) |
| Matched null: switches / weeks-or-months in market | 9 / 132 of 248 | 6 / 34 of 56 | 0 / 56 of 56 | 9 / 132 of 248 |
| Matched null verdict | **fails** | **fails** | **fails** | **fails** |
| Max round trips in a year, canonical | 1.50 | 1.49 | 0.84 | 1.49 |
| Max round trips in a year, full history | 1.99 | 1.98 | 0.75 | 1.94 |
| Turnover cap (≤ 4) | pass | pass | pass | pass |
| Smallest fill at CA$35 (need ≥ US$5.59) | US$24.79 | US$24.56 | US$3.61 | US$4.36 |
| Fills below 120 % of min at CA$35 | 0 of 9 | 0 of 8 | 6 of 11 | 3 of 12 |
| Min-order at CA$35 | pass | pass | **fail** | **fail** |
| Min-order at US$100 (reported) | pass (smallest US$99.11) | pass (smallest US$98.22) | pass (smallest US$14.44) | pass (smallest US$17.43) |
| **Round 2 verdict** | **FAIL** | **FAIL** | **FAIL** | **FAIL** |

### T4. Cost sensitivity, canonical (account view)

| Candidate | base 0.90 % | maker 0.50 % | slip30 1.10 % | maker+slip30 0.70 % | 2× 1.80 % |
|---|---|---|---|---|---|
| R2-01 | +200.1 % / 27.2 % / 0.85 | +212.4 % / 26.6 % / 0.87 | +194.2 % / 27.5 % / 0.84 | +206.2 % / 26.9 % / 0.86 | +174.3 % / 28.5 % / 0.79 |
| R2-02 | +166.9 % / 38.3 % / 0.73 | +175.6 % / 37.3 % / 0.75 | +162.7 % / 38.8 % / 0.72 | +171.2 % / 37.8 % / 0.74 | +148.4 % / 40.5 % / 0.69 |
| R2-03 | +123.7 % / 59.8 % / 0.60 | +130.5 % / 59.7 % / 0.62 | +122.0 % / 59.9 % / 0.60 | +128.7 % / 59.8 % / 0.61 | +116.0 % / 60.2 % / 0.59 |
| R2-04 | +199.0 % / 27.1 % / 0.88 | +211.1 % / 26.6 % / 0.90 | +193.0 % / 27.4 % / 0.86 | +205.0 % / 26.9 % / 0.89 | +173.2 % / 28.3 % / 0.82 |
| BTC buy-and-hold | +77.8 % / 67.0 % / 0.48 | +79.3 % / 67.0 % / 0.48 | +77.1 % / 67.0 % / 0.48 | +78.6 % / 67.0 % / 0.48 | — |

Cells: net return / max drawdown / Sharpe. Gate 1 and C11 verdicts are identical in every cost case: R2-01 Gate 1 fail in all four, R2-02 Gate 1 fail in all four, R2-03 Gate 1 fail in all four, R2-04 Gate 1 fail in all four.

### T5. Full history, base cost (supplementary; not the Gate 1 verdict)

| Candidate | Range | Net return | CAGR | Max DD | Sharpe | BTC B&H net / DD / Sharpe | Max RT/yr | Closed trades | C11 | Matched null | Gate 1 checks failed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R2-01 | 2015-01-01 → 2026-09-30 | +19679.7 % | +56.8 % | 64.6 % | 1.12 | +26035.8 % / 83.6 % / 1.04 | 1.99 | 12 | fails (84) | fails (90) | WF OOS ≥ 50 % IS, ≥ 100 trades, Top trade ≤ 30 % net, Beats C11 null |
| R2-02 | 2016-09-01 → 2026-09-30 | +21188.3 % | +70.1 % | 81.0 % | 1.10 | +14193.4 % / 83.6 % / 1.07 | 1.98 | 9 | fails (58) | fails (81) | WF OOS ≥ 50 % IS, ≥ 100 trades, Top trade ≤ 30 % net, Beats C11 null |
| R2-03 | 2015-01-01 → 2026-09-30 | +16795.9 % | +54.7 % | 68.0 % | 1.13 | +26035.8 % / 83.6 % / 1.04 | 0.75 | 0 | fails (0) | fails (82) | IS Sharpe ≥ 1.0, WF OOS ≥ 50 % IS, ≥ 100 trades, Fee ratio < 40 %, Top trade ≤ 30 % net, Force exits ≤ 30 % net, Beats C11 null |
| R2-04 | 2015-01-01 → 2026-09-30 | +9242.8 % | +47.1 % | 52.5 % | 1.18 | +26035.8 % / 83.6 % / 1.04 | 1.94 | 12 | fails (80) | beats (96) | WF OOS ≥ 50 % IS, ≥ 100 trades, Top trade ≤ 30 % net, Beats C11 null |

### T6. Round trips per calendar year, base

- R2-01 canonical: 2022 0.00, 2023 1.49, 2024 1.00, 2025 1.50, 2026 0.50
- R2-01 full_history: 2015 1.49, 2016 0.00, 2017 0.00, 2018 0.50, 2019 1.99, 2020 1.49, 2021 1.99, 2022 0.50, 2023 1.49, 2024 1.00, 2025 1.50, 2026 0.50
- R2-02 canonical: 2022 1.00, 2023 1.49, 2024 0.00, 2025 0.50, 2026 1.00
- R2-02 full_history: 2016 0.50, 2017 1.98, 2018 1.49, 2019 0.50, 2020 1.00, 2021 0.00, 2022 0.50, 2023 1.49, 2024 0.00, 2025 0.50, 2026 1.00
- R2-03 canonical: 2022 0.84, 2023 0.00, 2024 0.21, 2025 0.09, 2026 0.33
- R2-03 full_history: 2015 0.69, 2016 0.47, 2017 0.42, 2018 0.44, 2019 0.75, 2020 0.57, 2021 0.69, 2022 0.19, 2023 0.00, 2024 0.20, 2025 0.09, 2026 0.33
- R2-04 canonical: 2022 0.00, 2023 1.49, 2024 1.20, 2025 1.32, 2026 0.50
- R2-04 full_history: 2015 1.67, 2016 0.63, 2017 0.65, 2018 0.20, 2019 1.94, 2020 1.48, 2021 1.69, 2022 0.33, 2023 1.49, 2024 1.20, 2025 1.32, 2026 0.50

### T7. Canonical base trades

- **R2-01**: BTC 2023-01-16 → 2023-09-04 exit signal +5.54 USD (2 fills); BTC 2023-10-23 → 2024-08-05 exit signal +27.59 USD (2 fills); BTC 2024-10-21 → 2025-04-07 exit signal +6.70 USD (2 fills); BTC 2025-04-28 → 2025-11-10 exit signal +6.25 USD (2 fills); BTC 2026-08-24 → 2026-09-30 force exit +3.97 USD (2 fills)
- **R2-02**: ETH 2022-02-01 → 2022-05-01 exit signal -0.09 USD (2 fills); ETH 2023-07-01 → 2023-08-01 exit signal -1.43 USD (2 fills); BTC 2023-08-01 → 2025-12-01 exit signal +47.84 USD (2 fills); ETH 2026-04-01 → 2026-06-01 exit signal -4.58 USD (2 fills)
- **R2-03**: BTC 2022-02-01 → 2026-09-30 force exit +30.94 USD (12 fills)
- **R2-04**: BTC 2023-01-16 → 2023-09-04 exit signal +5.97 USD (3 fills); BTC 2023-10-23 → 2024-08-05 exit signal +27.86 USD (4 fills); BTC 2024-10-21 → 2025-04-07 exit signal +6.78 USD (2 fills); BTC 2025-04-28 → 2025-11-10 exit signal +5.19 USD (2 fills); BTC 2026-08-24 → 2026-09-30 force exit +3.95 USD (2 fills)

## Against the pre-registered hypotheses

| | Predicted | Result |
|---|---|---|
| R2-01 | Lower max DD and higher account Sharpe than buy-and-hold on 2015–2026; 1–3 round trips a year; fails Gate 1 on trade count and probably IS Sharpe; edge is drawdown, not return | **As predicted.** DD 64.6 % vs 83.6 %, Sharpe 1.12 vs 1.04, max 1.99 round trips a year, Gate 1 Sharpe 0.82 on the canonical range. Full-history return +19,680 % vs buy-and-hold +26,036 % |
| R2-02 | Avoids the 2018 and 2022 bears; beats buy-and-hold on DD and Sharpe; reacts late; most likely to breach the turnover cap | **Mixed.** It did side-step most of 2022 (canonical DD 38 % vs 67 %). Over 2016–2026 its DD was 81 %, barely below buy-and-hold's 84 %: the 12-month lookback held ETH into the 2018 crash. Sharpe 1.10 vs 1.07. Turnover peaked at 1.98, well under the cap. 3 of its 4 canonical trades lost money; one BTC trade made 115 % of net |
| R2-03 | Lower DD and higher Sharpe than buy-and-hold; headline Gate 1 numbers zero by the force-exit rule | **As predicted.** Canonical DD 59.8 % vs 67.0 %, Sharpe 0.60 vs 0.48. 0 closed trades, so Gate 1's Sharpe is 0.00. Small rebalances fail the CA$35 minimum order |
| R2-04 | Lowest DD and best Sharpe of the four; weekly rebalances may be too small for CA$35 | **As predicted.** Best Sharpe (0.88 canonical, 1.18 full) and lowest DD (27.1 %, 52.5 %). 3 of its 12 canonical fills are below the minimum at CA$35. In practice R2-04 is R2-01: BTC's realised vol was mostly ≤ 50 %, so the vol weight was usually capped at 1 and the trades are the same 5 |

## What this does and does not show

**Shows:**
- At ≤ 2 round trips a year, Tier-1 Kraken cost is small. The fee ratio is 6–8 %, and every
  cost case from 0.50 % to 1.80 % per fill leaves the ranking unchanged. Round 1's binding
  constraint (fee drag) is gone.
- A 200-day trend filter on BTC, checked weekly with a 5 % buffer, would have avoided most of the
  2022 bear and the late-2025 drawdown. It traded 4–5 times in 4.75 years, and every fill clears
  Kraken's minimum at CA$35.

**Does not show:**
- **That the timing is skill.** The matched null asks how often random timing with the same
  switch count and time in market does as well. On 2022–2026 the answer is 6–16 % of the time
  for the trend filters. With 9 switches there are very few independent decisions to test.
- **That Gate 1 could ever be passed by this family.** Under ADR-0021 as written it cannot be:
  - ≥ 100 closed trades is impossible at ≤ 4 round trips a year.
  - The walk-forward test cannot see a holding period longer than its 3-month OOS window. Each
    window starts flat and drops its own force exit, so only the short whipsaw trades are left:
    1 trade in 3 of 15 windows, all losers. Pooled OOS Sharpe is −1.25 against a full-range
    0.82.
  - The 30 % single-trade rule cannot hold with 4 trades.

  These are properties of the gate applied to this kind of strategy. They are not evidence about
  the strategy either way. Whether a low-turnover strategy should get its own gate is a decision
  for the operator, in a new ADR, in a later round. It was not changed here.
- Anything about the future. Two bear markets and two bull legs in the canonical range is a small
  sample of regimes.

## Erratum found during this run: the random-entry null's draws were not per candle

The first scored run's C11 null was degenerate. `null.uniforms` turned timestamps into seconds
with `astype("int64") // 1e9`, which assumes nanoseconds. Under the pinned image's pandas 3.0.5,
the Kraken feather candles load at second resolution, so every candle in a seed got the same draw
(one draw per seed).

- **Fixed in `11299cd`:** the seconds are now computed via a `Timedelta`, so nanosecond input is
  unchanged. Regression test: `test_null_uniforms_do_not_depend_on_datetime_resolution`.
- **Reports rebuilt with `run --recompute`.** This mode writes nothing to the registry and refuses
  unless every trial's recorded Gate 1 Sharpe, trade count and full daily-return series are
  reproduced bit for bit. They were. Only the C11 null changed: R2-01 and R2-04 move from "fails"
  to "beats" (the old p95 was 0.62–0.67, the corrected 0.73–0.75). No Gate 1 or round-2 verdict
  changed, since every candidate fails on other checks. The first run's output is kept in
  `services/research/runs/round2-first-run-null-bug/` (git-ignored, local).
- **Round 1 is affected too.** Freqtrade 2026.8 gives millisecond dates, so the round-1 null drew
  one value per ~11.6 days: 27 distinct draws in 300 daily candles, and ~70 candles per draw on
  4h. The random-entry null table in [`05-first-candidates.md`](05-first-candidates.md)
  therefore did not use independent per-candle entries as ADR-0021 specifies. **Round 1's Gate 1
  verdicts do not depend on it:** every round-1 candidate also failed IS Sharpe, OOS/IS and the
  single-trade rule. That document is left as the historical record. Re-scoring round 1's nulls
  is a follow-up for the operator to decide on; it would not add trials, because it would be a
  report rebuild like the one above.

## Reproducing

```bash
scripts/research-round2.sh coverage                 # data check (WP-A)
scripts/research-round2.sh run --seeds 200 --recompute   # rebuild these reports; never writes the registry
```

A plain `run` now refuses: every round-2 trial is scored, and re-running cannot reset N.
Registry backups (README table): `registry-2026-11-01-round2-scored.sqlite`, SHA-256
`20ec2514d1dd85661d9b7bea53d558e9a7e360fde3b70cf1dd9a9c25ee337aaa`, 26 trials, 26 results.
