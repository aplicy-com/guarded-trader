# ADR-0005: Low-frequency strategies only (4h/1d bars), maker-preferred, ≤3 positions

## Status

Accepted — 2026-09-09

## Context and problem statement

At $100 principal, a Kraken taker round-trip costs roughly 0.5% of the
position; any edge under about 0.7% per trade is fee noise, not alpha
(research review §1.5). Separately, the Alpha Arena evidence shows
over-trading and fee drag as a dominant failure mode for LLM-influenced
strategies (research review §3). What trading frequency and position
policy should the system operate under?

## Decision drivers

- Fee economics at $100 scale make high-turnover strategies mathematically
  unviable before considering any edge at all.
- The evidence base's own "what survivors do" pattern (research review §5)
  is explicitly low-turnover.
- Correlation between BTC/ETH and most alts (risk register M3) means a
  small position count with a correlation guard is more honest about real
  exposure than a larger nominal count would be.
- Simpler, lower-frequency strategies are easier for the LLM research loop
  to generate, backtest meaningfully, and keep within the ≤6-tunable-
  parameter overfitting cap (NFR5).

## Considered options

- **Low-frequency (4h/1d bars), maker-preferred, max 2–3 open positions
  with a correlation guard**
- Intraday/high-frequency (minute-level or faster) signals
- No explicit frequency or position-count cap, left to each strategy

## Decision outcome

Chosen option: **low-frequency only.** Strategies operate exclusively on
4-hour or daily bars; orders are placed maker-preferred wherever the
strategy allows; at most 2–3 positions open at once, with correlated pairs
(BTC/ETH and similar) counted as a single exposure unit for risk-budget
purposes. Enforced in Freqtrade config
(`04-architecture/execution-freqtrade.md`) and in the Conductor's
correlation guard (`04-architecture/conductor.md`).

### Rationale

Directly addresses the dominant observed failure mode (over-trading/fee
drag) and matches the fee-economics constraint at $100 scale. Also keeps
backtest/walk-forward runs computationally cheap and strategy logic simple
enough for meaningful human + LLM review.

### Consequences

**Good:**
- Removes an entire class of failure (fee-drag death by a thousand cuts)
  by construction, not by hoping a strategy happens to trade little.
- Simpler strategies are easier to validate against the overfitting
  defence (NFR5) and easier for a half-asleep human to reason about during
  an incident.

**Bad / accepted trade-offs:**
- The system cannot react to intraday moves or capture short-lived
  opportunities — accepted, since the evidence base says chasing those at
  this scale is a net loser, not a missed opportunity.
- Caps the strategy universe; some genuinely good higher-frequency ideas
  from the LLM research loop would be out of scope by design. Acceptable
  given the fee-economics constraint is structural, not a matter of
  strategy quality.

## More information

If principal ever scales meaningfully beyond $100 (out of scope for
Phase 1–4, and R1 forbids top-ups regardless), the fee-economics
constraint changes and this ADR should be explicitly revisited rather than
silently loosened.
