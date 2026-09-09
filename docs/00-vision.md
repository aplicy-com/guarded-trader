# 00 — Vision

## Thesis

Frontier LLMs, given direct control of live trading decisions, lose money
(see [`research/01-research-review.md`](research/01-research-review.md) §3).
What survives, in retail and institutional practice alike, is deterministic
execution with strict, independently-enforced risk limits — where "AI" is at
most a researcher or optimiser, never the order router.

This project tests a narrow, falsifiable claim: **a small ($100), real-money
crypto trading system, where a deterministic risk/execution engine does all
trading and an LLM only proposes and reviews strategies in a nightly,
gated research loop, can operate for months without violating its own risk
limits or losing its principal — and be fully transparent about the result,
win or lose.**

The system is called **Conductor** (the orchestration/research/ledger
layer) driving **Freqtrade** (the execution/risk engine) against **Kraken**
(the exchange). See [`ADR-0001`](05-adr/0001-freqtrade.md) and
[`ADR-0002`](05-adr/0002-kraken.md).

## Non-goals

- **Not a new execution engine.** We build on Freqtrade's dry-run/live
  parity and built-in protections rather than writing an order router from
  scratch.
- **Not an LLM order-placer.** The LLM never places, modifies, or cancels
  an order, at any phase, on any timeframe. See
  [`ADR-0003`](05-adr/0003-llm-never-orders.md).
- **Not high-frequency or tick-level trading.** Strategies operate on 4h/1d
  bars only. See [`ADR-0005`](05-adr/0005-low-frequency-only.md).
- **Not scaled beyond $100 in Phase 1–4.** No top-ups to principal (R1); no
  fundraising, no managing anyone else's money, no signal service.
- **Not a claim of alpha.** We treat "LLM beats the market" claims as
  unproven per the KTD-Fin findings (research review §3) and measure our
  own results net of passive market exposure where practical.
- **Not investment, tax, or legal advice** for anyone but the author's own
  bookkeeping.
- **Not aiming to compete with institutional quant infrastructure.** The
  goal is a safe, well-instrumented, honest experiment — boring
  infrastructure, low turnover, long validation periods (research review
  §5).
- **Not free to run.** The $100 principal is not this project's real
  budget. The nightly LLM research loop has its own ongoing compute cost,
  entirely independent of trading capital and capped separately (R6) —
  and that cost is tracked and reported as honestly as the trading results
  are, not treated as a rounding error.

## Success criteria

Success is layered, matching the promotion path in
[`ADR-0003`](05-adr/0003-llm-never-orders.md) and
[`08-paper-exit-criteria.md`](08-paper-exit-criteria.md):

1. **Docs-first bar (Phase 1, this scaffold):** every capital rule, risk,
   architectural decision, and emergency procedure is written down and
   reviewed by the human operator before any exchange-connected code
   exists.
2. **Paper bar (Phase 3):** at least one strategy passes backtest →
   walk-forward → 3-week continuous dry-run against the numeric exit
   criteria in `08-paper-exit-criteria.md`, with zero risk-engine
   violations and zero unhandled halts.
3. **Live bar (Phase 4):** the system runs live at 25% then 100%
   allocation without breaching R1–R4 (`02-requirements.md`), i.e. the
   principal is never at risk beyond its own hard loss limits, and every
   halt correctly requires human re-enable.
4. **Ongoing bar (Phase 5):** strategies are re-validated on a fixed
   cadence (research review: every 4–6 weeks), the system remains net
   profitable after fees over a rolling window, or is honestly reported as
   not — and the full history (including losing periods) stays public.

Failure is an acceptable outcome of this experiment. An unbounded loss of
principal beyond the configured hard limits, or a silent/undetected halt,
is not — those are the conditions this entire docs set exists to prevent.

## TBD

- Exact quantitative long-run "success" threshold beyond Phase 4 (e.g.
  target CAGR, Sharpe) — TBD (Phase 5), deliberately not set now to avoid
  incentivising overfitting to a number before the system has any live
  track record.
