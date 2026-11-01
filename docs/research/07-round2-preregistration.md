# Research round 2 — pre-registration: very-low-turnover candidates at real Kraken cost

**Frozen 2026-11-01, before any round-2 strategy code or backtest exists.** The machine-readable
source of truth is [`services/research/candidates-round2.json`](../../services/research/candidates-round2.json);
this document explains it. If the two disagree, the JSON wins. The trial registry hashes the
JSON byte for byte, and the round-2 runner refuses to score a trial whose spec has changed since
it was registered. No candidate may be added, dropped or re-tuned after results exist. A changed
idea is a new trial in a new round.

## 1. Question

Round 1 ([`05-first-candidates.md`](05-first-candidates.md)) found no candidate that clears
Gate 1 at Kraken Tier-1 cost. The dominant failure was fee drag at a 0.90 % per-fill cost. Round
2 asks a narrower question: **does a very low-turnover strategy (≤ 4 round trips in any
calendar year) pass Gate 1 at real Kraken cost?**

## 2. Gate 1 is used exactly as written, and it is expected to fail on trade count

Gate 1 is ADR-0021's, unchanged
([`0021-cost-consistent-gate-1-and-random-entry-null.md`](../05-adr/0021-cost-consistent-gate-1-and-random-entry-null.md),
[`08-paper-exit-criteria.md`](../08-paper-exit-criteria.md)). It is computed by the existing
`research_harness.cli.gate1` function on each candidate's **canonical base trial**:
2022-01-01 → 2026-10-01, 0.90 % per fill.

**Known before running.** Gate 1 requires **≥ 100 closed trades over the canonical timerange**.
The round-2 turnover cap allows at most ~19 round trips over those 4.75 years. Every round-2
candidate therefore **fails Gate 1 by construction**, whatever its returns. This conflict was
raised with the operator before anything was frozen. On 2026-11-01 the operator chose to run
Gate 1 exactly as written anyway, and to report the economics in full. No gate was changed. If
a low-turnover gate is wanted, it needs a new ADR that supersedes ADR-0021, written by the
operator, in a later round.

Other Gate 1 criteria that bind hard on these strategies, also known in advance:

| Criterion | Why it binds here |
|---|---|
| IS Sharpe ≥ 1.0 over 2022–2026 | The range opens with the 2022 bear and ends in the Nov 2025 – Sep 2026 drawdown. A long-or-flat BTC rule is unlikely to reach 1.0 |
| No single trade > 30 % of net | With ~5–15 trades, one bull-market trade usually is most of the profit |
| Force exits excluded | R2-03 never leaves the market, so its only trade is the final force exit. Its headline Gate 1 figures are therefore **zero trades and a flat equity curve**. That is the rule as written, not a bug |

## 3. Candidates (parameters fixed; nothing tuned)

All four are long-or-flat, unleveraged, spot, USD-quoted. A decision is taken at the daily
close (UTC) of a check day and filled at the next day's open. Weekly = Sunday close;
monthly = last calendar day's close.

| ID | Rule | Params | Check |
|---|---|---|---|
| **R2-01** BTC trend filter | Flat → buy BTC (100 %) if close > SMA200 × 1.05. In → sell to cash if close < SMA200 × 0.95 | `sma_days` 200, `band` 0.05 | weekly |
| **R2-02** Dual momentum | Hold whichever of BTC/ETH has the higher 12-month return (tie → BTC), if that return > 0; else cash | `lookback_days` 365 | monthly |
| **R2-03** Vol target | BTC weight = min(1, 0.50 / realised 60-day annualised vol). Rebalance only if relative drift > 20 % | `vol_target` 0.5, `vol_window_days` 60, `drift_band` 0.2 | monthly |
| **R2-04** R2-01 × R2-03 | R2-01's on/off state. When on, R2-03's weight and drift rule | R2-01's and R2-03's values, no new ones | weekly |

R2-04 has five parameters in the registry, but each one reuses an R2-01 or R2-03 value, so no
new degree of freedom is added (≤ 3 new each; ≤ 6 total per ADR-0021).

**Definitions** (exact wording in the JSON, `definitions`):
- SMA = mean of the last 200 daily closes, decision day included.
- Realised vol = sample std (ddof = 1) of the last 60 daily log returns × √365.
- 12-month return = close / close 365 calendar days earlier − 1.
- Relative drift = |current weight − target| / target, where current weight = position value
  ÷ equity at the decision close.

**Pre-registered hypotheses** (full text in the JSON):
- R2-01 beats buy-and-hold on drawdown, probably not on IS Sharpe ≥ 1.0.
- R2-02 avoids the 2018/2022 bears but reacts late, and is the candidate most likely to breach
  the turnover cap.
- R2-03 lowers drawdown versus buy-and-hold, and its headline Gate 1 numbers are zero by the
  force-exit rule.
- R2-04 has the lowest drawdown, but weekly drift rebalances may be too small for Kraken's
  minimum order at CA$35.

## 4. Benchmark

BTC buy-and-hold: all equity into BTC/USD at the first day's open, sold at the last close, at
the same cost case. Also the harness's fee-free `metrics.buy_and_hold`. Not a trial.

## 5. Costs and balances

| Case | Fee | Slippage | Per fill | Use |
|---|---|---|---|---|
| **base** | 0.80 % (Tier-1 taker) | 0.10 % | **0.90 %** | Gate 1 (= `config.backtest-costs.json`) |
| maker | 0.40 % | 0.10 % | 0.50 % | sensitivity, never a gate |
| slip30 | 0.80 % | 0.30 % | 1.10 % | sensitivity |
| maker_slip30 | 0.40 % | 0.30 % | 0.70 % | sensitivity |
| stress_2x | — | — | 1.80 % | ADR-0021's mandatory 2× report, inside every base trial |

Fees are modelled as Freqtrade does: a buy costs `notional × (1 + c)` and a sell returns
`notional × (1 − c)`.

**Start balance: CA$35 = US$25.01**, at the USD/CAD mid of 1.39963 measured 2026-11-01. That is
the amount credited to Kraken on 2026-10-31. **Sensitivity: US$100**, the R1 principal. The
engine is fractional, so returns, Sharpe and drawdown are identical at both balances. The
balance enters only the minimum-order check (§8).

## 6. Quote currency: USD (measured)

Measured on 2026-11-01 from Kraken's public Ticker and Depth endpoints: 20 samples, 15 s apart,
no key ([`round2-evidence/quote-spreads-2026-11-01.json`](round2-evidence/quote-spreads-2026-11-01.json),
script `scripts/kraken_quote_spreads.py`). FX fee from Kraken's public fee schedule
(kraken.com/features/fee-schedule, read 2026-11-01): "Stablecoin, Pegged Token & FX Pairs",
lowest tier **0.20 % maker / 0.20 % taker**. Such trades do not count toward 30-day volume.

| Pair | Median spread | Max spread | US$25 / US$100 market buy vs mid | ordermin | costmin |
|---|---|---|---|---|---|
| BTC/USD | 0.013 bp | 0.013 bp | 0.006 bp / 0.006 bp | 0.00006 BTC | 0.5 USD |
| BTC/CAD | 2.98 bp | 3.05 bp | 1.49 bp / 1.49 bp | 0.00006 BTC | 1 CAD |
| ETH/USD | 0.044 bp | 0.79 bp | 0.022 bp / 0.022 bp | 0.002 ETH | 0.5 USD |
| ETH/CAD | 1.03 bp | 14.3 bp | 0.51 bp / 0.51 bp | 0.002 ETH | 1 CAD |
| USD/CAD | 1.93 bp | 3.14 bp | 0.98 bp / 0.98 bp | 5 USD | 1 CAD |

What the measurement shows:
- At these sizes every order fills at top of book, so cost = half-spread.
- BTC/CAD costs ~1.5 bp more per fill than BTC/USD.
- Converting CAD → USD costs ~0.21 % once: 0.20 % fee + ~1 bp. Converting back costs the same.
- BTC/CAD ÷ (BTC/USD × USD/CAD) = −0.8 bp, so there is no exploitable basis.

**Decision: USD.** At ≤ 8 fills a year the CAD route saves at most ~0.1–0.3 % over a one-to-two-year
pilot. That is less than the 0.10 % slippage already charged on every single fill. USD keeps
[ADR-0008](../05-adr/0008-usd-quote-currency.md) unchanged, so no new ADR is needed. It also
means the backtest prices exactly the book that would be traded. The one-time conversion is a
pilot cost, not a strategy cost.

## 7. Data (ADR-0020), coverage confirmed

Kraken official OHLCVT archive, 1440-minute candles, snapshot `6f4979b22d6aaafe`. The latest
available archive release ends **2026-09-30**; the 2026Q4 incremental does not exist yet.
Report: [`round2-evidence/data-coverage-2026-11-01.json`](round2-evidence/data-coverage-2026-11-01.json)
(`scripts/research-round2.sh coverage`, network-less sandbox).

| Pair | First candle | Range checked | Missing days | Fraction |
|---|---|---|---|---|
| BTC/USD | 2013-10-06 | 2014-01-01 → 2026-09-30 (incl. warm-up) | 10, all in 2014 | 0.21 % |
| BTC/USD | | 2015-01-01 → 2026-09-30 | 0 | 0 % |
| ETH/USD | 2015-08-07 | 2015-08-07 → 2026-09-30 | 6 (5 in 2015, 2018-01-12) | 0.15 % |
| ETH/USD | | 2016-09-01 → 2026-09-30 | 1 (2018-01-12) | 0.03 % |
| both | | 2021-01-01 → 2026-09-30 | 0 | 0 % |

The worst case is 0.21 %, far below the 5 % stop threshold. A missing day becomes a flat,
zero-volume candle at the previous close, which is what Freqtrade does on load.

**Timeranges:**
- **canonical** `20220101-20261001`: the Gate 1 range.
- **full history** (supplementary): `20150101-20261001` for R2-01/03/04, and `20160901-20261001`
  for R2-02. R2-02's first 12-month ETH return exists at 2016-08-31.

## 8. Method

**Engine.** A daily portfolio backtester in `services/research/src/research_harness/round2/`
(written in WP-B). Freqtrade cannot express R2-02's cross-pair switch or R2-03's drift
rebalancing without large custom code. The engine emits **Freqtrade-shaped trade records**
(orders, fees, exit reasons), so every Gate 1 number comes from the existing, tested harness
functions, unchanged: `metrics.compute_metrics`, `walkforward.windows`/`summarise`,
`null.verdict`, `null.uniforms`, `dsr.deflated_sharpe`, `cli.gate1`, `registry.Registry`. It
runs in the same network-less sandbox (`scripts/research-round2.sh`).

**Walk-forward:** anchored **and** rolling, 12-month IS / 3-month OOS, 15 OOS windows on the
canonical range. Each window is its own backtest that starts flat, with warm-up from earlier
candles. OOS Sharpe is pooled.

**Nulls**, 200 seeds each:
- **C11 random-entry null (Gate 1).** Keeps the candidate's exits, sizing, rebalancing, check
  schedule, costs and single slot. Entries become seeded Bernoulli draws on check days at the
  candidate's own rate. A random entry is never drawn on a check day where the candidate's own
  exit fires. The rate is calibrated exactly as `research_harness.cli` does it. The verdict is
  `null.verdict`: Sharpe > p95 **and** MDD < median **and** top-trade share ≤ median.
- **Matched switching null (round-2 requirement).** Same number and order of in/out runs, same
  starting state, same total check periods in and out of the market. The run lengths are
  random.
  - R2-02: the pair of each in-market run is random.
  - R2-03: the entry is kept, the rebalance dates are random, and the candidate's own target
    weights are applied in random order.

  The candidate's **account-view** Sharpe must exceed the null's 95th percentile.

**Turnover cap (round-2 requirement).** Round trips per calendar year = Σ |fill notional| ÷
pre-fill equity ÷ 2, force exits excluded. More than 4.0 in **any** calendar year fails. It is
checked on the canonical base trial and on the full-history base trial.

**Minimum order (round-2 requirement).** Every non-force-exit fill in the canonical base trial is
sized as (fill ÷ pre-fill equity) × start balance. It must be ≥ 120 % of
max(costmin, ordermin × mid) on 2026-11-01. That threshold is US$5.59 for BTC/USD (0.00006 ×
77,700 × 1.2) and US$5.44 for ETH/USD. Pass/fail is at CA$35. US$100 is reported.

**Deflated Sharpe.** Reported on every trial against the registry's N. N counts **every**
registered trial: the 6 from round 1 plus the 20 here, 26 in total. Not gated (ADR-0021).

**Reported for every trial:**
- account view: net return, CAGR, max drawdown, Sharpe;
- the same for BTC buy-and-hold;
- round trips per calendar year, closed trades, fills;
- the Gate 1 checks;
- both nulls;
- DSR.

## 9. Trials

Twenty trials, all registered before any of them runs: 4 candidates × {base, maker, slip30,
maker_slip30 on canonical; base on full history}. The registry is append-only, and every one of
the 20 counts toward N whatever its result. Registry rows: §11.

## 10. Decision rule (frozen)

A candidate **passes round 2** only if all four hold:
1. Gate 1 passes on its canonical base trial.
2. The turnover cap holds on both base trials.
3. It beats its matched null.
4. It passes the minimum-order check at CA$35.

- **If ≥ 1 passes:** ADR-0024 names it, and a pilot plan is written under
  `docs/06-runbooks/go-live-pilot.md`. Nothing in the pilot is executed.
- **If none passes:** a write-up and the pause record in `docs/07-roadmap.md` are updated
  ("round 2 done, trigger 2 still unmet").

## 11. Registry entries

Appended after `scripts/research-round2.sh prereg` ran against the commit that froze the spec;
the spec is unchanged.

Registered 2026-11-01 against commit `66d1ce6826544b2a71fcc6c1b91d94e3964264b3` (the commit that froze `candidates-round2.json`). Registry trial count: **6 → 26**. None was scored at registration. Each row's `freqtrade_version` field reads `none: round-2 daily portfolio engine (research_harness.round2); prereg commit 66d1ce6826544b2a71fcc6c1b91d94e3964264b3`.

| Trial | Trial id | Per fill | Timerange | Strategy hash (first 16) |
|---|---|---|---|---|
| `R2-01/base/canonical` | `5f5412be679a` | 0.90 % | 20220101-20261001 | `7676952b367a7ab5` |
| `R2-01/maker/canonical` | `28f4b5bd8a19` | 0.50 % | 20220101-20261001 | `9285c169c6cf371d` |
| `R2-01/slip30/canonical` | `322c76d3c7f6` | 1.10 % | 20220101-20261001 | `dd398351e055cdb9` |
| `R2-01/maker_slip30/canonical` | `64dd0962f166` | 0.70 % | 20220101-20261001 | `06ed815764a70fb9` |
| `R2-01/base/full_history` | `32c9e0d6d37a` | 0.90 % | 20150101-20261001 | `6953479eb0a21068` |
| `R2-02/base/canonical` | `f6d1ab43032e` | 0.90 % | 20220101-20261001 | `6e4b41f2650546b7` |
| `R2-02/maker/canonical` | `0da61ba0962f` | 0.50 % | 20220101-20261001 | `94902cd194265ea1` |
| `R2-02/slip30/canonical` | `a11cd1124259` | 1.10 % | 20220101-20261001 | `c9e3acbe772a6d9b` |
| `R2-02/maker_slip30/canonical` | `cf6fa729217f` | 0.70 % | 20220101-20261001 | `5b80a6de66abf58d` |
| `R2-02/base/full_history` | `53822c41a49b` | 0.90 % | 20160901-20261001 | `2d223d54b6f620dc` |
| `R2-03/base/canonical` | `bf8cbf1840d2` | 0.90 % | 20220101-20261001 | `014857a5b636db64` |
| `R2-03/maker/canonical` | `5d23a5695a1d` | 0.50 % | 20220101-20261001 | `6998294386c1e87e` |
| `R2-03/slip30/canonical` | `14436eaac0c3` | 1.10 % | 20220101-20261001 | `f605806e812e261f` |
| `R2-03/maker_slip30/canonical` | `40d82676300b` | 0.70 % | 20220101-20261001 | `01cdd6ad7b11407b` |
| `R2-03/base/full_history` | `3b9dfb83dfdc` | 0.90 % | 20150101-20261001 | `befcad007f4bfeae` |
| `R2-04/base/canonical` | `628a1e14f258` | 0.90 % | 20220101-20261001 | `a789be3a1593a4cf` |
| `R2-04/maker/canonical` | `e69457ba2ccc` | 0.50 % | 20220101-20261001 | `4fe3e6d7d809f339` |
| `R2-04/slip30/canonical` | `6de2c6b50009` | 1.10 % | 20220101-20261001 | `fc4e6836d04b1ff5` |
| `R2-04/maker_slip30/canonical` | `d00ac7ba85c9` | 0.70 % | 20220101-20261001 | `a522a3325d17457d` |
| `R2-04/base/full_history` | `5d32afa7056c` | 0.90 % | 20150101-20261001 | `1bffdfe8a02def1b` |
