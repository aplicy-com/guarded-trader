# ADR-0003: The LLM never places, modifies, or cancels an order

## Status

Accepted — 2026-09-09

## Context and problem statement

Every public live-money experiment with a frontier LLM as the direct
trading decision-maker has lost money in aggregate (Nof1 Alpha Arena
Seasons 1 and 1.5: pooled portfolio down roughly a third, only 6 of 32
model-runs profitable; failure modes were over-trading, fee drag, bad
sizing, mistimed entries — research review §1, §3). Separately, a
leakage-controlled 2026 benchmark (KTD-Fin) found LLM "stock-picking
alpha" claims largely explained by passive market/style exposure once
memory leakage is controlled for. Given this, what authority should the
LLM have over live trading decisions?

## Decision drivers

- Direct evidence that LLM-as-order-router loses money live, repeatedly,
  across multiple independent experiments and model providers.
- Non-determinism: the same prompt produced radically different trading
  decisions run to run in Alpha Arena S1.5 — a live order path cannot
  tolerate that variance.
- The capital rules (R1–R4) require hard, auditable, non-negotiable
  limits — those cannot depend on an LLM's in-context judgement on a given
  night.
- Adoptable ideas from the academic multi-agent literature (FinMem,
  FinCon, TradingAgents) — layered memory, role separation, structured
  reflection — are valuable for *research quality*, independent of whether
  the LLM is ever allowed to route an order.

## Considered options

- **LLM proposes; deterministic engine executes** (research/reviewer role
  only, gated promotion).
- LLM has direct, real-time control over order placement (rejected by the
  evidence above).
- LLM has direct control but bounded by hard-coded position/size limits
  checked at the same layer (rejected — conflates two trust domains in one
  code path, harder to audit, no case in the evidence base of this working
  live).
- No LLM involvement at all (rejected — discards the genuinely useful
  research/reflection ideas from the literature; also not what this
  project is testing, see `00-vision.md`).

## Decision outcome

Chosen option: **LLM proposes; deterministic engine executes.** The LLM
(Claude) operates only in a nightly research loop, producing candidate
strategy code, parameter changes, reviews, and post-mortems. Every
candidate passes backtest → walk-forward validation → 3-week paper
(dry-run) → 25% allocation → 100% allocation before it controls any real
capital, and every stage transition is decided by deterministic code
(the promotion-gate engine in Conductor), not by LLM judgement in the
moment. See `04-architecture/conductor.md` for the pipeline and
`02-requirements.md` R1–R4 for the capital rules this protects.

### Rationale

Matches the one pattern in the evidence base that has worked at scale:
deterministic, well-instrumented execution with AI as at most an optimiser
(research review §5). Converts non-determinism from a live-trading risk
into a research-loop-only property — a candidate that "randomly" comes out
different tonight is just a different candidate to gate, not a different
live outcome.

### Consequences

**Good:**
- Live trading behaviour is fully deterministic and auditable — every
  order traces to a pinned, git-hashed strategy version, never to an
  in-the-moment LLM decision.
- A prompt-injection attempt via external data fed to the research loop
  (risk register L4) cannot reach the order path even if it somehow
  altered LLM output, because that output still has to pass deterministic
  gates.
- Aligns directly with R4: hard loss limits cannot be argued around by an
  LLM, because the LLM has no path to touch them.

**Bad / accepted trade-offs:**
- Slower to react to genuinely novel market conditions than a live-LLM
  system would be, by design — we treat this as a feature (research
  review: "surviving retail systems" are low-turnover, not fast-reacting).
- Strategy quality is bounded by what passes backtest/walk-forward, which
  cannot fully substitute for live judgement — accepted, since the
  evidence base says live LLM judgement on order placement is a net
  negative, not a net positive, today.

## More information

If future evidence (tracked informally via updates to the research
review) demonstrates a live-LLM-execution approach that reliably survives
walk-forward and paper validation better than the gated approach, this
ADR should be revisited explicitly — not silently bypassed.
