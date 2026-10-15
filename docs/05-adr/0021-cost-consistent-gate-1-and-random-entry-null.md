# ADR-0021: Cost-consistent Gate 1 — Tier-1 taker fees, a multi-year trade minimum, and a random-entry null

## Status

Accepted — 2026-10-14. Amends [`docs/08-paper-exit-criteria.md`](../08-paper-exit-criteria.md)
Gate 1 and Gate 2 and [`docs/phase-3-plan.md`](../phase-3-plan.md) 3B-1/3B-3/3C. Does not change
ADR-0003, ADR-0007 or any capital rule.

## Context and problem statement

The evidence review of 2026-10-14 (`docs/research/evidence-review-2026-10/`) found three
problems with the gates as written:

1. **The fee was wrong.** Gates were calibrated to 0.16 % maker / 0.26 % taker. Kraken's official
   fee schedule, fetched and re-verified on 2026-10-14, puts a < $2,500 30-day-volume account at
   **Tier 1: 0.40 % maker / 0.80 % taker**. A $100 account cannot leave Tier 1. A round trip
   therefore costs 0.8–1.6 % before slippage, and a trade must gross 2–4 % on average for fees to
   stay under 40 % of profit. Re-running the reference strategy changing *only* the fee moves its
   2-year result from −2.81 % to −45.94 % (`docs/research/03-baseline-backtest.md`).
2. **"≥ 20 trades in 8 weeks" selects for the trade frequency the cost evidence rejects.** With
   two slots at ~50 % utilisation it implies a ~2.8-day average hold; no cost-aware study supports
   a 2–3-day hold on BTC-type spot clearing a 1.0–1.8 % round trip, and slower evaluation beat
   faster after 20 bp costs (Clare et al.). Twenty trades also cannot support a statistical claim
   about edge (04-validation-upgrades.md §13).
3. **Nothing separated the entry signal from market beta and exit timing**, and **nothing knew
   how many candidates had been tried**, so an IS Sharpe ≥ 1.0 floor would eventually be passed
   by noise (expected best-of-noise Sharpe ≈ 1.66 at N = 300).

## Decision drivers

- Gates must be computed at a fee we can actually get, with stops and exits priced as they fill.
- The statistical trade count belongs on the multi-year backtest, where it can mean something.
- A candidate's entry rule must be shown to add something beyond "be long crypto, exit like this".
- Every scored candidate must be counted, so deflation is possible at all.
- Keep what already works: the 30 % single-trade dominance rule, force-exit exclusion, ≤ 6
  parameters, daily-equity Sharpe, OOS ≥ 50 % of IS.

## Considered options

- **Re-base Gate 1 on Tier-1 taker cost, move the trade minimum to the canonical backtest, add
  the random-entry null and a trial registry, keep 20 trades only as the paper fill-rate sample**
  (chosen)
- Keep "≥ 20 trades in 8 weeks" and lower the fee assumption back (rejected: the fee is a
  verified fact, not a choice)
- Drop any trade minimum (rejected: too few trades makes every other statistic meaningless)
- Gate on DSR now (rejected for now: no calibrated threshold exists for a solo nightly loop with
  a handful of trials; it is reported on every run and becomes a gate in Phase 3)

## Decision outcome

### Cost basis (all backtests)

- One value, `fee` in `services/freqtrade/user_data/config.backtest-costs.json`:
  **0.009 per side = 0.80 % Tier-1 taker + 0.10 % slippage.** Every backtest merges that file;
  `--fee` is no longer passed anywhere. Changing the assumption is a one-line, reviewed commit.
- Every fill is priced as taker, including limit entries and exits, because Freqtrade's
  backtester fills a limit order whenever price touches it and so overstates maker fills.
  A maker-priced run (0.40 % + slippage) may be shown for comparison, never used for a gate.
- Every candidate is also run at **2× the fee** and the result reported (not yet a gate).

### Gate 1, as amended

| Criterion | Rule |
|---|---|
| Data | Kraken's official archive (ADR-0020), on the **canonical timerange** fixed in `services/research/candidates.json`: currently 2022-01-01 → 2026-10-01, which contains the 2022 bear and the Nov 2025 – Sep 2026 drawdown. Changing it is a new trial for every candidate. Resolves the "minimum backtest history" TBD. |
| Pre-registration | The candidate's hypothesis and parameters are committed and written to the trial registry **before** it is backtested. The registry is append-only. |
| Tunable parameters | ≤ 6 (unchanged) |
| IS Sharpe | ≥ 1.0, daily mark-to-market equity basis, over the canonical timerange (unchanged floor) |
| Walk-forward | Anchored **and** rolling, 12-month IS / 3-month OOS, **≥ 8 OOS windows each**; pooled OOS Sharpe ≥ 50 % of IS in both (pooled = concatenated OOS daily returns, not an average of per-window ratios) |
| **Minimum trade count** (replaces "≥ 20 trades in 8 weeks") | **≥ 100 closed trades over the canonical timerange**, force exits excluded. Trades per OOS window are reported; a per-window minimum is TBD (Phase 3). |
| **Fee ratio** | fees ÷ gross winning P&L **< 40 %** at the cost basis above (was a Gate 2 criterion only) |
| **Random-entry null (C11)** | Candidate daily-equity Sharpe **> 95th percentile** of 200 seeded random-entry runs, **and** candidate max drawdown **< null median**, **and** candidate top-trade share of gross winning P&L **≤ null median**. The null keeps the candidate's exits, stop, sizing, fee and slots; its entry rate is calibrated so its mean trade count matches the candidate's; random entries are never placed on a candle where the candidate's own exit fires. |
| No single-trade dominance | No single trade, and not the force-exit group as a whole, > 30 % of net profit (unchanged) |
| Force exits | Excluded from every headline figure, reported separately (unchanged) |
| Deflated Sharpe | **Reported** on every run against the registry's trial count N and cross-trial Sharpe dispersion. Threshold TBD (Phase 3); the review's suggestion is DSR ≥ 0.80. |

### Gate 2 (paper), as amended

The window still ends at ≥ 3 continuous weeks **and** 20 closed trades, or at 8 weeks. The
20 trades are a **fill-rate sample size** (how often maker orders fill, realised slippage), not a
target: no strategy is expected or rewarded to reach it, and the canonical backtest's own trade
rate (trades per 8 weeks) is the number paper trading is compared against under "backtest
consistency". The research loop's brief no longer asks for "≥ 20 trades / 8 weeks".

### Consequences

**Good:**
- Gates are computed at a cost the account will actually pay.
- The trade-count rule no longer pushes candidates toward the holding periods that fees destroy.
- A candidate that only harvests BTC beta or exit timing fails the null even if its Sharpe clears 1.0.
- The registry makes the number of attempts a recorded fact, so DSR, and later PBO, are computable.

**Bad / accepted trade-offs:**
- Pricing every fill as taker is pessimistic for a maker-preferred design; the paper phase measures
  the real maker fill rate and can justify a revision.
- ≥ 100 trades over ~4.75 years is a looser per-year bar (~21/year) than the review's "≥ 100 over
  3 years"; it is kept at 100 because that is the number the review gives, and the canonical
  timerange is longer than 3 years by design.
- 200 null seeds multiply backtest time by ~200; minutes for 1d strategies, ~25 minutes for a 4h
  strategy with a per-candle custom stop.
- DSR with a handful of trials and a dispersion estimated from them is noisy; it is reported, not
  gated, until Phase 3.

## More information

- Implementation: `services/research/` (harness), `scripts/research-harness.sh` (sandbox:
  no network, read-only repo and data, no capabilities, no `.env`).
- Follow-up validation items not done here (04-validation-upgrades.md P1/P2): PBO via CSCV over
  the registry, Harvey–Liu haircut, block-bootstrap drawdown distribution, parameter plateau,
  `lookahead-analysis`/`recursive-analysis` wrapper and static lint, taker-only and 0.25 %
  slippage stress variants, SPA/StepM, `--timeframe-detail` on finalists, paper fill-rate logger,
  regime/decay monitor, CPCV. Listed in `docs/research/05-first-candidates.md`.
- First results under these gates: `docs/research/05-first-candidates.md`.
