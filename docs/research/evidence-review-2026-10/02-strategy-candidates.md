# Strategy Candidates: Twelve Pre-Registered Hypotheses for the Research Loop

Purpose: concrete, Freqtrade-implementable candidates that fit every system constraint (Kraken spot, long-only, no leverage, 4h or 1d bars, ≤ 6 parameters, 1–2 positions, maker-preferred), each with pre-registered parameter ranges, trade-frequency arithmetic against the ≥ 20-trades-in-8-weeks gate, breakeven cost at both fee levels, and the evidence grade inherited from `01-evidence-review.md`.
Date: 2026-10-14
How to read the grades: **A** = replicated, out-of-sample, after costs. **B** = single solid study, or replicated outside crypto. **C** = anecdotal, vendor, preprint or in-sample only. "Untested — hypothesis" means no cost-aware evidence exists in any asset class.

---

## Conventions used in every candidate

**Cost figures.** Round-trip cost = entry fee + exit fee + 0.10% slippage per side (the slippage figure is an assumption; no Kraken small-order slippage data exists). Low = 0.16% maker / 0.26% taker (the system's current assumption). High = 0.40% maker / 0.80% taker (Kraken's official Tier-1 page fetched 2026-10-14, see `01` §0). "m/m" = limit entry and limit exit; "m/t" = limit entry, market or stop exit.

| Pattern | Low fees + slippage | High fees + slippage | Avg gross profit per trade for fee ratio < 40% (fees only), low → high |
|---|---|---|---|
| m/m | 0.52% | 1.00% | 0.80% → 2.00% |
| m/t | 0.62% | 1.40% | 1.05% → 3.00% |
| t/t | 0.72% | 1.80% | 1.30% → 4.00% |

**Trade-frequency arithmetic.** Expected trades in 8 weeks ≈ slots × utilisation × 56 days ÷ average hold in days, plus whipsaw entries. Slots = 2. Utilisation for a long-flat trend rule on BTC-type assets is ≈ 0.5 (Han, Kang & Ryu's best rule was invested ~48% of the time ([AUT PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf))). Because SOL–BTC correlation is 0.75 and XRP–BTC 0.55 ([CME Group](https://www.cmegroup.com/articles/2025/diversifying-crypto-portfolios-with-xrp-and-sol.html)), the five pairs flip together more often than not, so five pairs do not give five independent trade streams.

**A structural warning that applies to every candidate.** The evidence in `01` says slower exits and slower evaluation beat faster ones after 20 bp costs ([Clare et al.](https://openaccess.city.ac.uk/17842/8/BLACKBOX%20%20%20SSRN-id2126476.pdf)), and that at Tier-1 fees a trade must gross 2–4% on average to keep fees under 40% of profit. Twenty trades in eight weeks with two slots means an average hold of ≈ 2.8 days at 50% utilisation. Nothing in the evidence base supports a 2–3-day hold on BTC-type spot clearing a 1.0–1.8% round trip. **The ≥ 20-trades gate as written selects for exactly the trade frequencies the cost evidence rejects.** Every candidate below reports honestly which way it fails; `04` proposes re-expressing the gate.

**Freqtrade hooks.** Entry and exit signals go in `populate_entry_trend` / `populate_exit_trend` on closed candles; catastrophe stops in `stoploss`; any path-dependent exit in `custom_stoploss` or `custom_exit`; sizing in `custom_stake_amount` (a documented Freqtrade callback; its handling of Kraken's `costmin` $0.50 for tiny stakes was not verified in the notes and must be tested in dry-run). Keep `minimal_roi = {}` or the default `{"0": 10}` so ROI never caps a trend trade ([Freqtrade configuration](https://www.freqtrade.io/en/stable/configuration/)). Every candidate inherits the catastrophe stop as a parameter because the capital rules require a hard loss limit; it is placed far enough (15–25%) that the evidence on "stops subtract value" is not triggered on normal paths.

---

## C01 — Weekly-scale time-series momentum, long-flat, trend-flip exit

**Leads with:** entry (the only return effect with more than one after-cost data point).

**Hypothesis.** BTC and large-cap returns over 1–4-week lookbacks continue for 1–3 weeks; a long-when-positive / cash-otherwise rule evaluated at the daily close captures this while sitting out bears. Han, Kang & Ryu's long-only TSMOM "mostly beat the market" after 15 bp per trade with Sharpe 1.51 for the (28-day lookback, 5-day hold) pair ([AUT PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)); Liu & Tsyvinski's 1-week return predicts 1–3 weeks ahead (t = 3.7–4.5) gross ([NBER w24877](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)); Mercik et al. find 7-day momentum still positive at 0.4%/trade but weakening after 2021 ([Crypto Factor Zoo](https://open.icm.edu.pl/bitstreams/21636cf6-61df-4fb5-9ae4-4195d592cd26/download)). Expect the effect to be smaller than published and concentrated in bull legs.

**Rules.** Entry: at daily close, `close > close.shift(L)` (L-day return positive) and the pair is among the strongest ≤ 2 by L-day return if more than 2 qualify. Exit: L-day return ≤ 0 at daily close (signal flip), filled as a limit at next open. Stop: catastrophe only. Sizing: fixed fraction of equity per slot (C04 replaces this).

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| L (lookback, days) | 21 | 7–28 | The range with independent support; shorter is sub-cost, longer is unsupported |
| eval_tf | 1d | 1d or 4h-on-daily-boundary | Clare et al.: slower evaluation beats faster after costs |
| catastrophe_stop | −20% | −15% to −25% | Hard loss limit required by capital rules; wide so it rarely fires |
| slot_fraction | 0.5 | 0.25–0.5 | Two slots of one correlated exposure |

**Trade frequency.** Avg hold ≈ 10–20 days (signal persistence of a 3-week lookback). 2 × 0.5 × 56 ÷ 14 ≈ 4 completed trades, plus 2–6 whipsaw entries → **≈ 4–10 trades in 8 weeks on 1d**; the 4h variant with L expressed in bars (6L) adds whipsaws → **≈ 6–14**. Over a 3-year backtest: ≈ 60–120 trades. The ≥ 20-in-8-weeks gate fails unless L ≤ ~5 days, which is the regime Shen et al. show is sub-cost ([Reading eprint](https://reading-9.eprints-hosting.org/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf)).

**Fee survival.** Trend-flip exits can be limit orders → m/m: breakeven 0.52% (low) / 1.00% (high); fee-ratio gate needs avg gross ≥ 0.8% / 2.0%. With 10–20-day holds in assets that move 15–20% over 20 days, winners of 5–15% and losers of 2–5% give plausible averages of 1–3%: survives low fees, marginal at high fees.

**How it fails.** Post-2021 decay (two subperiod splits agree); bull-regime concentration (one or two trades > 30% of profit); chop under a falling 200DMA (Nov 2025–Sep 2026) producing serial whipsaws; the 4h variant trades too often.

**Grade:** B. **Gate most likely to fail:** ≥ 20 trades / 8 weeks; second, single-trade > 30% of profit.

---

## C02 — Long-term moving-average regime filter, monthly evaluation

**Leads with:** entry/regime (an overlay more than a standalone).

**Hypothesis.** A 150–250-day MA (Faber-style 10-month rule) evaluated at month- or week-end keeps a long-only portfolio flat through 2018/2022/2025–26-type bears at very low turnover. Multi-asset evidence is strong but gross and non-crypto: Clare et al. 2016 report developed-equity Sharpe 0.30 → 0.76 and MDD 60.7% → 16.3% for a 10-month MA long/flat rule ([City PDF](https://openaccess.city.ac.uk/id/eprint/17841/8/TREND%20IS%20YOUR%20FRIEND%20%20%20SSRN-id2126478.pdf)); on the S&P 500 at 20 bp the monthly 200-day rule gives Sharpe 0.58 vs 0.31 buy-and-hold with the advantage coming "mainly from lower volatility" ([Blackbox PDF](https://openaccess.city.ac.uk/17842/8/BLACKBOX%20%20%20SSRN-id2126476.pdf)). BTC-specific evidence is vendor-only (Summitward's vol-targeted 200-day rule: Sharpe 0.89, MDD −10.4% at 1–4 bp ([Summitward](https://summitward.com/learn/crypto-trend-following))) and K33's 2026 commentary notes BTC spent 189 days below a *declining* 200DMA ([The Block](https://www.theblock.co/post/401991/not-all-200-day-moving-averages-are-equal-k33-argues-februarys-60k-low-still-marks-cycles-maximum-drawdown)).

**Rules.** Entry: at the chosen evaluation close, `close > SMA(N) × (1 + band)`. Exit: `close < SMA(N) × (1 − band)` at an evaluation close. Stop: catastrophe only.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| N (MA days) | 200 | 150–250 | Faber/Clare region; plateau expected, not a point |
| eval_cadence | weekly close | weekly or monthly | Clare: monthly > daily after costs |
| band | 2% | 0–4% | Hysteresis against whipsaw at the MA |
| catastrophe_stop | −25% | −15% to −25% | Required hard limit |

**Trade frequency.** 2–6 round trips per year per pair; 2 slots → **≈ 0–3 trades in 8 weeks**, ≈ 15–30 over 3 years. Fails the trade-count gate decisively; also too few trades for the Sharpe gates to be estimable.

**Fee survival.** m/m 0.52% / 1.00%; captures are tens of percent, so fee ratio ≪ 40% at either level. This is the most fee-robust candidate.

**How it fails.** Whipsaw around a flat MA; late entry after V-bottoms (misses the first 20–30% of a recovery); 2025–26 shows long stretches flat. It is better used as the regime gate for C01/C03/C06 than as a standalone.

**Grade:** C for BTC specifically; B for the drawdown direction. **Gate most likely to fail:** ≥ 20 trades / 8 weeks.

---

## C03 — Donchian N-day-high breakout with M-day-low exit

**Leads with:** entry.

**Hypothesis.** Buying a new 20–50-day high and exiting on a 10–20-day low is a self-contained trend rule whose exit is already a slow trailing stop. The only OOS tracking found is Quantpedia's cost-free extension through August 2024 where the 10–50-day "MAX" rule "still works" and "all lookbacks remain worthwhile" ([Quantpedia](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/)); Clare et al. find the plain 200-day breakout (Sharpe 0.56) beats every stop-overlaid variant on the S&P ([Blackbox PDF](https://openaccess.city.ac.uk/17842/8/BLACKBOX%20%20%20SSRN-id2126476.pdf)). Rozario et al.'s walk-forward instability warning applies to parameter choice ([ar5iv](https://ar5iv.labs.arxiv.org/html/2009.12155)).

**Rules.** Entry: daily close > highest high of prior N days (limit at next open; accept that breakouts often fill as taker). Exit: daily close < lowest low of prior M days. Stop: catastrophe. Optional C02 regime gate.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| N (entry lookback) | 30 | 20–50 | Quantpedia's tested range |
| M (exit lookback) | 15 | 10–20, M < N | Asymmetric channel = slow exit |
| regime_gate | on | on/off | C02 filter, tested as a binary |
| catastrophe_stop | −20% | −15% to −25% | Required |

**Trade frequency.** One entry per 3–6 weeks per pair in trending regimes, none in ranges; 2 slots → **≈ 3–8 in 8 weeks**; ≈ 40–80 over 3 years.

**Fee survival.** Entry often taker (breakout chasing), exit limit → m/t pattern: 0.62% / 1.40%; fee-ratio gate needs 1.05% / 3.0% avg gross. Holds of 2–6 weeks make this plausible at low fees, marginal at high.

**How it fails.** False breakouts in chop (the 2026 range); profits concentrated in 1–2 runs; taker entries at Tier 1 double the entry cost.

**Grade:** C. **Gate most likely to fail:** ≥ 20 trades; then single-trade concentration.

---

## C04 — Volatility-scaled exposure overlay (capped at 1×)

**Leads with:** exposure/exit design — sizing as the primary risk control.

**Hypothesis.** The drawdown of a long-flat trend rule on a 70–80%-vol asset is a sizing problem: hold `min(1, σ_target/σ_realised) × slot_fraction` of equity, so exposure shrinks when vol spikes and the strategy never holds a full-size position into a crash. Harvey et al. show vol targeting raises equity/credit Sharpe (0.40 → 0.48–0.51), "consistently reduces the likelihood of extreme returns" across 60+ assets, and costs at most ~5 round trips per year at the fastest estimator ([Duke PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf)); Man Group reports ~40 Sharpe points on BTC scaled to 30% vol, no costs or drawdowns given ([Man Group](https://www.man.com/insights/crypto-too-hot-to-handle)); Grobys et al. find vol management cuts kurtosis of crypto momentum from 121.8 to 68–106 but leaves tail exponents unchanged ([Springer](https://link.springer.com/article/10.1007/s11408-025-00474-9)); the only crypto decomposition attributes most drawdown reduction to the scaling rather than the signal ([Summitward](https://summitward.com/learn/crypto-trend-following), grade C). The capped (≤ 1×) version is untested anywhere.

**Rules.** At entry (C01/C02/C03/C06 signal): stake = equity × slot_fraction × min(1, σ_target / σ_realised(window)). Rebalance only if the implied weight drifts by more than `band` *and* the resulting order exceeds Kraken `costmin` $0.50 with a fee < 5% of the adjustment — otherwise hold. Exit per the base candidate. Implement with `custom_stake_amount`; optional `adjust_trade_position` for scale-downs only.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| σ_target (annualised) | 20% | 10–30% | Man uses 30%; Summitward 10%; lower = smaller positions |
| vol_window (days) | 30 | 20–60 | Harvey: 20–90-day half-lives all work |
| band | 25% relative | 15–40% | Limits rebalance turnover at tiny size |
| max_fraction | 0.5 | 0.25–1.0 | Cap per slot; never above 1× total |

**Trade frequency.** Inherits the base candidate's count; rebalances add ≤ 5 orders/year per slot if the band is respected.

**Fee survival.** Rebalance orders are limit → m/m 0.52% / 1.00% on the adjusted notional only. The real constraint is size: at $20 equity and σ_realised = 80%, a 20% target gives a $2.50 position per slot; fees of ≈ $0.01–0.02 per side are affordable but the position rounds near `costmin`. At $100 the positions are $12.50 and workable.

**How it fails.** Gives up most of the raw return (Summitward's trend+vol BTC CAGR 6.2% vs 73.5% buy-and-hold); at $20 the target sizes round to zero; vol estimated over a window shorter than the hold lags crashes (Oct 11 2025 −13% in a day). It cannot be judged by return — judge it by MDD, vol-of-vol and the block-bootstrap drawdown distribution in `04`.

**Grade:** B as a stabiliser (A outside crypto); C for any return claim. **Gate most likely to fail:** IS Sharpe ≥ 1.0 (returns shrink with exposure); not the trade-count gate.

---

## C05 — Signal-flip-only exit: the one-variable A/B against the known result

**Leads with:** exit (removal of the stop).

**Hypothesis.** The system's EMA(20/50) cross with a fixed 2×ATR stop lost 2.8% with 65–72% drawdown over two years. The evidence says the stop, not the cross, is the likelier culprit: Kaminski & Lo show short-horizon stops have negative stopping premiums even before costs ([MIT DSpace](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf)); Clare et al. find purchase-cost and trailing stops on MA crossovers unchanged or worse at 20 bp, with the 50/200 crossover falling from 10.62% to 7.45% with a stop, and conclude "a change of trend is the best stop loss" ([Blackbox PDF](https://openaccess.city.ac.uk/17842/8/BLACKBOX%20%20%20SSRN-id2126476.pdf)); Freqtrade's backtester fills stops at the exact price and checks them before ROI, so the −2.8% is an upper bound on the stopped design live ([Freqtrade backtesting](https://www.freqtrade.io/en/stable/backtesting/)). Re-run the identical strategy with the ATR stop removed and compare on the same data; then add the weekly-evaluation variant.

**Rules.** Entry: EMA(fast) crosses above EMA(slow) at close. Exit: EMA(fast) crosses below EMA(slow) at close, limit at next open. Stop: catastrophe only. Variant B: evaluate the cross only at weekly close.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| fast | 20 | 10–30 | Keep the known configuration first |
| slow | 50 | 40–100 | — |
| eval_cadence | as tested | daily / weekly | Clare: monthly > daily |
| catastrophe_stop | −20% | −15% to −25% | Replaces the 2×ATR stop |

**Trade frequency.** On 1d, EMA 20/50 crosses ≈ 6–10 times/year per pair → 2 slots → **≈ 4–8 in 8 weeks**; on 4h ≈ 3–5 crosses/month per pair → **≈ 15–30 in 8 weeks**, whipsaw-heavy. The 4h variant meets the trade gate and fails the fee gate; the 1d variant is the reverse.

**Fee survival.** m/m 0.52% / 1.00%. A 4h EMA 20/50 cross on BTC captures ≈ 1–2% per trade on average (whipsaws dominate) — below the 2.0% high-fee requirement. On 1d, captures of 3–8% are plausible.

**How it fails.** The cross itself has no edge (Rozario's walk-forward finding); then removing the stop only converts many small losses into fewer larger ones with the same expectancy. That is a legitimate and cheap negative result.

**Grade:** B (Clare et al., single index). **Gate most likely to fail:** IS Sharpe ≥ 1.0 (the cross may simply have no edge); 4h variant fails fee ratio.

---

## C06 — Wide ATR chandelier trail, evaluated at daily close only

**Leads with:** exit.

**Hypothesis.** A *wide* trail (3–4 × ATR from the highest close since entry) behaves like a trend flip with fewer parameters and no indicator lag; narrow trails are the ones the equity evidence rejects. The only crypto result is Bui & Nguyen's ablation on 150+ perps at 4 bp, where removing an α = 2.5 ATR trail cut Sharpe 2.41 → 1.68 and the plateau spanned α ∈ [2.0, 3.5] ([arXiv 2602.11708](https://arxiv.org/html/2602.11708v1)) — but Sharpe fell to 1.62 at 12 bp and the design was never tested at 20+ bp. Clare et al.'s 12% trailing stop on the S&P lowered Sharpe 0.56 → 0.54 at 20 bp ([Blackbox PDF](https://openaccess.city.ac.uk/17842/8/BLACKBOX%20%20%20SSRN-id2126476.pdf)). Evaluate the trail only at the daily close, because Freqtrade's backtest uses the candle *high* as `current_rate` in `custom_stoploss` and would otherwise flatter the result ([strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/)).

**Rules.** Entry: C01 or C03 signal. Exit: daily close < (highest close since entry − k × ATR(n)); implemented in `custom_exit` on the daily close, not as an intrabar stop. Stop: catastrophe.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| k (ATR multiple) | 3.5 | 2.5–4.0 | Bui & Nguyen plateau, shifted wider for higher fees |
| n (ATR period, days) | 20 | 14–30 | Standard; should show a plateau |
| entry_L | 21 | 7–28 | From C01 |
| catastrophe_stop | −20% | −15% to −25% | Required |

**Trade frequency.** Slightly higher than C01 (earlier exits in pullbacks): **≈ 6–12 in 8 weeks on 1d**.

**Fee survival.** Exit is a close-based signal → limit order → m/m 0.52% / 1.00%. At k = 3.5 and daily ATR ≈ 3–4% of price, the trail sits 10–14% below the high, so winners are 10%+ and losers 3–6%; average gross 1.5–3% plausible.

**How it fails.** k narrow enough to matter is k narrow enough to whipsaw; the Bui & Nguyen cost curve (−0.4 Sharpe per +4 bp) extrapolated to Tier 1 predicts Sharpe below 1; the 4h version will be killed by the high-as-rate bias in backtests and by fees live.

**Grade:** C (B− in the note; preprint, perps, low fees). **Gate most likely to fail:** OOS ≥ 50% of IS (parameter instability in k).

---

## C07 — Fail-fast time stop (untested — hypothesis)

**Leads with:** exit.

**Hypothesis.** If a trend entry has not shown profit within N days, the autocorrelation that justified it has not materialised, and exiting early at a small loss avoids the long losers; the Kaminski–Lo condition (stops help only where ρ ≥ Sharpe at the stop horizon) could hold for "no follow-through" trades specifically ([MIT DSpace](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf)). **No cost-aware evidence exists for time stops on trend systems in any asset class**; Freqtrade supports them via `minimal_roi` `"<N>": -1` or `custom_exit` ([Freqtrade configuration](https://www.freqtrade.io/en/stable/configuration/)). Include because it is cheap and falsifiable, not because it is supported.

**Rules.** Entry: C01. Exit: C01 flip, OR if `current_profit < X` after N days since entry. Stop: catastrophe.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| N (days) | 7 | 5–15 | Shorter than the expected hold |
| X (profit threshold) | 0% | −1% to +2% | "Has it done anything?" |
| entry_L | 21 | 7–28 | From C01 |
| catastrophe_stop | −20% | −15% to −25% | Required |

**Trade frequency.** Increases count by truncating losers: **≈ 8–16 in 8 weeks on 1d** — closer to the gate, at the price of more round trips.

**Fee survival.** Exits at the time stop are often small losses plus a full round trip; at high fees each time-stop exit costs 1.0% on top of the loss. Average gross per trade falls; fee ratio rises. Pre-register the prediction: it improves MDD and fails the fee-ratio gate at high fees.

**How it fails.** It cuts slow-starting winners in a right-skewed asset; it adds turnover; and it introduces a parameter (N) with no economic anchor, inviting overfit.

**Grade:** Untested — hypothesis (C at best). **Gate most likely to fail:** fee ratio < 40%.

---

## C08 — Breakeven lock then wide trail (untested — hypothesis)

**Leads with:** exit / profit protection.

**Hypothesis.** Keep the catastrophe stop until the trade is up Y%, then move the stop to entry + round-trip cost (so a winner cannot become a fee-negative trade), then trail widely. This is Freqtrade's `trailing_only_offset_is_reached = True` with `trailing_stop_positive_offset = Y` and `trailing_stop_positive = D`; the docs warn the offset must sit below `minimal_roi` or ROI fires first ([Freqtrade stoploss](https://www.freqtrade.io/en/stable/stoploss/)). **No study tests breakeven stops with costs**; the nearest evidence (Lei & Li: trailing stops cut variance but not return ([CXO summary](https://www.cxoadvisory.com/technical-trading/using-trailing-stop-losses-to-reduce-risk)); Clare et al.: trailing lowers Sharpe slightly) points to a neutral-to-negative outcome. Pre-register that prediction.

**Rules.** Entry: C01. Stop: catastrophe until profit ≥ Y; then stop = entry × (1 + cost_rt); then trail at D below the highest close, evaluated at daily close in `custom_stoploss`.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| Y (lock trigger) | 8% | 5–12% | Must exceed several round trips |
| D (trail distance) | 12% | 8–15% | Wide, per the evidence against tight trails |
| entry_L | 21 | 7–28 | From C01 |
| catastrophe_stop | −20% | −15% to −25% | Required |

**Trade frequency.** ≈ C01 (**4–10 in 8 weeks on 1d**); trail exits are taker if placed on exchange, maker if executed at the close via `custom_exit`.

**Fee survival.** m/t if on-exchange: 0.62% / 1.40%; m/m if close-evaluated. The breakeven lock converts some would-be winners into ~0% trades that still paid a round trip — a hidden fee drag the fee-ratio gate will expose.

**How it fails.** Stopped-at-breakeven trades that then resume (Detko et al.'s "miss the rebound" pattern); more exits = more fees; D interacts with Y to create a two-parameter overfit surface.

**Grade:** Untested — hypothesis (C). **Gate most likely to fail:** fee ratio < 40%; then OOS ≥ 50% of IS.

---

## C09 — Funding-rate crowding overlay (de-risk only)

**Leads with:** risk / exit — it only ever blocks entries or exits positions.

**Hypothesis.** Persistently high perpetual funding marks crowded leveraged longs and precedes liquidation cascades; a spot-only system should not open new longs into that condition. Schmeling, Schrimpf & Todorov: carry averages 7–10%/yr, spikes above 40–60%, and "high carry predicts future price crashes" ([BIS WP 1087](https://www.bis.org/publ/work1087.htm)); a 10% rise in standardised carry predicts a 22% rise in sell liquidations relative to open interest over the next month ([CEPR](https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets)). As a *timing* rule the evidence is C: the BitMEX funding-reversion test shows 44–53% hit rates and no significant predictive power ([BitMEX](https://www.bitmex.com/blog/xbtusd-funding-mean-reversion-strategy)). Data: Binance `/fapi/v1/fundingRate` (no key, ≤ 1,000 rows per call) ([Binance docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)), fetched by deterministic code, stored with content hashes, and treated as data, not instructions.

**Rules.** Compute the 30-day mean of BTCUSDT 8h funding. If it exceeds the trailing W-day P-th percentile, block new entries in all five pairs (one exposure group); optionally exit open positions. Never use low/negative funding as an entry signal.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| P (percentile) | 90 | 85–95 | "Multi-month high" |
| W (window, days) | 180 | 90–365 | Trailing distribution |
| action | block_entry | block_entry / block_and_exit | Test the cheaper version first |
| base | C01 | C01/C03 | Overlay |

**Trade frequency.** Reduces the base count by the fraction of time the flag is on (≈ 10% by construction).

**Fee survival.** No additional orders unless `block_and_exit`; then one m/m exit per episode.

**How it fails.** Funding regimes shifted after the 2024 ETF launch and micro-futures changes (CME carry rose ~11% after May 2021 per the CEPR column); cross-venue funding differs materially ([Zhivkov](https://www.mdpi.com/2227-7390/14/2/346)); the flag may simply switch off during the most profitable bull legs. Pre-register: it should lower MDD and lower return.

**Grade:** B as a crash-risk proxy; C as a timing rule. **Gate most likely to fail:** IS Sharpe ≥ 1.0 (it removes return without adding any).

---

## C10 — Daily trend filter gating 4h entries

**Leads with:** entry (multi-timeframe).

**Hypothesis.** A slow daily filter removes the whipsaw of a faster 4h entry while the 4h bar supplies the trade count the gate demands. The only numerical test is Quantpedia's BTC D1-MACD filter on 1h MACD entries (Dec 2018–Nov 2025): the filter roughly halved MDD (−23.9% → −12.4%) and raised Sharpe 0.33 → 0.80, but on ~1,000 trades earning 6.6%/yr with no costs ([Quantpedia](https://quantpedia.com/how-to-design-a-simple-multi-timeframe-trend-strategy-on-bitcoin/)) — 1,000 trades × 1.0% round trip = 1,000% cumulative cost against ~46% cumulative gross. Rozario et al. found intraday MA rules unprofitable even before costs ([ar5iv](https://ar5iv.labs.arxiv.org/html/2009.12155)). Use `merge_informative_pair()` for the daily series (plain `.merge()` leaks the daily close into the 4h bar ([Freqtrade strategy customization](https://www.freqtrade.io/en/stable/strategy-customization/))).

**Rules.** Filter: daily close > SMA(N_d) (or daily L-day return > 0). Entry: 4h close > highest high of prior N_4h bars, only while the filter is on. Exit: 4h close < lowest low of prior M_4h bars, or filter turns off. Stop: catastrophe.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| N_d (daily filter) | 100 | 50–200 | Slow filter |
| N_4h (entry bars) | 30 (5 days) | 18–60 | Breakout on 4h |
| M_4h (exit bars) | 12 (2 days) | 6–30 | Faster exit |
| catastrophe_stop | −15% | −10% to −20% | Required |

**Trade frequency.** 4h breakouts recur every 1–3 weeks per pair while the filter is on; 2 slots → **≈ 15–30 in 8 weeks**. This is the only candidate that comfortably meets the trade gate.

**Fee survival.** Entries chase breakouts (taker), exits at close (maker) → m/t 0.62% / 1.40%; needs 1.05% / 3.0% avg gross. Holds of 2–5 days on 4h bars capture ≈ 1–3% on average. Fails the fee-ratio gate at high fees almost by construction; marginal at low.

**How it fails.** Exactly the way Quantpedia's version does once costs are applied; and the 4h exit lookback M will be fitted to the chop of 2026.

**Grade:** C. **Gate most likely to fail:** fee ratio < 40%.

---

## C11 — Random-entry null baseline (mandatory for every candidate)

**Leads with:** nothing — it is the control.

**Hypothesis.** A candidate's exit, stop and sizing logic applied to *random* entries at the same per-pair entry rate produces a distribution of Sharpe, MDD and fee ratio; the candidate's entry rule must beat that distribution, or the "edge" is the exit/sizing/market-beta, not the signal. Gençay's protocol includes a random null and a buy-and-hold benchmark as required reporting ([arXiv 2608.27734](https://arxiv.org/pdf/2608.27734)); Lei & Li's stop-loss study used random entry dates for the same reason ([CXO summary](https://www.cxoadvisory.com/technical-trading/using-trailing-stop-losses-to-reduce-risk)). In a long-only system most of any backtest's return is BTC beta, which this isolates.

**Rules.** For each candidate, generate S seeds. For each seed, replace `populate_entry_trend` with Bernoulli entries whose rate matches the candidate's observed entry rate per pair over the canonical timerange; keep everything else identical (exit rule, catastrophe stop, sizing, fees, slippage). Record the null distribution of daily-equity Sharpe, MDD, fee ratio and top-trade share.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| S (seeds) | 200 | 100–500 | Enough for a stable 95th percentile |
| rate_match | per pair | per pair / pooled | Preserve exposure time |
| benchmark | BTC buy-and-hold | + equal-weight 5-pair | Second null |

**Trade frequency / fee survival.** Identical to the candidate by construction.

**Gate.** Candidate daily-equity Sharpe > 95th percentile of the null distribution AND candidate MDD < null median AND candidate top-trade share not worse than null median. A candidate that beats the null only on Sharpe and not on MDD is harvesting the exit's beta-timing, which is fine to know.

**Grade:** n/a (method, grade B per Gençay). **Gate most likely to fail:** candidates C05/C10 are predicted to be indistinguishable from this null.

---

## C12 — Volatility-regime long-flat (discrete vol-spike exit)

**Leads with:** exit — a step-function version of C04 that is cheaper at tiny size.

**Hypothesis.** Rather than continuously rebalancing to a vol target (which at $20–$100 produces sub-`costmin` orders), exit entirely when realised vol crosses a high percentile and re-enter only when it has fallen back and the trend is positive. Mechanism from Harvey et al.: in assets with a leverage effect, vol scaling "acts like time-series momentum" and cuts tails ([Duke PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf)); Man Group shows BTC 3-month drawdowns scale with realised vol (~50% at 30–60% vol, ~70% at ~130%) ([Man Group](https://www.man.com/insights/crypto-too-hot-to-handle)); Kaya & Mostowfi's long-only low-vol selection with a 5–10% monthly stop improved Sharpe after 0.175% + 0.5% spread ([ZHAW PDF](https://digitalcollection.zhaw.ch/bitstream/11475/23853/3/2022_Kaya-Mostowfi_Low-volatility-strategies-cryptocurrencies_frl.pdf)). Whether BTC has the equity-like leverage effect or the commodity-like null is unknown.

**Rules.** σ = realised vol over V days. Exit (and block entries) when σ > P_high-th percentile of its trailing 365-day distribution. Allow re-entry when σ < P_low-th percentile and the C01 signal is positive. Stop: catastrophe.

| Parameter | Default | Sane range | Why |
|---|---|---|---|
| V (vol window, days) | 20 | 10–30 | Responsive but not noisy |
| P_high | 80 | 70–90 | Spike threshold |
| P_low | 50 | 40–60 | Hysteresis |
| entry_L | 21 | 7–28 | From C01 |

**Trade frequency.** Adds 1–3 vol-exit/re-entry cycles per quarter → **≈ 6–12 in 8 weeks on 1d**.

**Fee survival.** Close-evaluated exits → m/m 0.52% / 1.00%. Vol-spike exits often happen *after* the first leg of a crash (vol is lagging), so they can lock in losses and then miss the V-bottom; pre-register that the benefit is MDD, not return.

**How it fails.** Lagging vol estimate; two percentile parameters invite fitting to the Oct-2025 and Feb-2026 episodes; in a grinding bear with low vol it stays long.

**Grade:** C (B for the mechanism outside crypto). **Gate most likely to fail:** IS Sharpe ≥ 1.0; OOS stability of P_high.

---

## Comparison

| ID | Name | Leads with | Params | Bars | Trades / 8 wk (est.) | Breakeven, low / high (pattern) | Grade | Likeliest gate failure |
|---|---|---|---|---|---|---|---|---|
| C01 | Weekly TSMOM long-flat, flip exit | Entry | 4 | 1d (4h variant) | 4–10 (6–14) | 0.52% / 1.00% (m/m) | B | ≥ 20 trades |
| C02 | 150–250-day MA regime, monthly eval | Regime | 4 | 1d | 0–3 | 0.52% / 1.00% (m/m) | C (B direction) | ≥ 20 trades |
| C03 | Donchian N-high / M-low | Entry | 4 | 1d | 3–8 | 0.62% / 1.40% (m/t) | C | ≥ 20 trades |
| C04 | Vol-scaled exposure overlay (≤ 1×) | Exposure | 4 | 1d | inherits | 0.52% / 1.00% on adjustments | B stabiliser | IS Sharpe |
| C05 | EMA cross, flip-only exit (A/B vs known) | Exit | 4 | 1d / 4h | 4–8 / 15–30 | 0.52% / 1.00% (m/m) | B | IS Sharpe (1d); fee ratio (4h) |
| C06 | Wide ATR chandelier, close-evaluated | Exit | 4 | 1d | 6–12 | 0.52% / 1.00% (m/m) | C | OOS ≥ 50% IS |
| C07 | Fail-fast time stop | Exit | 4 | 1d | 8–16 | 0.52–0.62% / 1.00–1.40% | Untested | Fee ratio |
| C08 | Breakeven lock + wide trail | Exit | 4 | 1d | 4–10 | 0.62% / 1.40% (m/t) | Untested | Fee ratio |
| C09 | Funding-rate crowding block | Risk | 4 | 1d + 8h funding | ≤ base | none added | B proxy / C timing | IS Sharpe |
| C10 | Daily filter + 4h breakout | Entry | 4 | 4h + 1d | 15–30 | 0.62% / 1.40% (m/t) | C | Fee ratio |
| C11 | Random-entry null | Control | 3 | as base | as base | as base | method | — |
| C12 | Vol-regime long-flat (discrete) | Exit | 4 | 1d | 6–12 | 0.52% / 1.00% (m/m) | C | IS Sharpe |

Seven of twelve (C04–C09, C12) lead with exit, exposure or risk design. No candidate meets both the ≥ 20-trades and fee-ratio gates at high fees; C10 is the only one that meets the trade gate at all, and it is the one the cost evidence most clearly rejects.

## Test these three first

1. **C01** — the only entry effect with more than one after-cost study behind it; cheapest to implement; its failure on the trade-count gate is informative about the gate, not just the strategy.
2. **C04 applied to C01** — the evidence's primary drawdown lever; judged on MDD, vol-of-vol and the bootstrap drawdown distribution, not on return.
3. **C05** — a one-variable A/B against the system's only known result; if removing the 2×ATR stop does not change the −2.8% / 65–72% outcome, the cross has no edge and the lesson "exits matter most" is falsified cheaply.

Run **C11** against each of the three before any gate is read; a candidate that does not beat its own random-entry null has nothing to promote.
