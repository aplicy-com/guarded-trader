# ADR-0007: Candidate code admission gate for LLM-generated strategy code

## Status

Accepted — 2026-09-09

## Context and problem statement

[`ADR-0003`](0003-llm-never-orders.md) established that the LLM never
places, modifies, or cancels an order — but it did not address a
narrower, prior question: LLM-generated *strategy code* still has to run
somewhere before it can even be evaluated, and Freqtrade strategies are
plain Python classes with the full power of the Python runtime (arbitrary
imports, file I/O, network calls, subprocess execution). A backtest or
walk-forward run of LLM-generated code, executed naively in the same
environment as everything else, is itself an unreviewed code-execution
event. The order-authority boundary ADR-0003 draws does not automatically
cover *code execution* — a strategy candidate could, in principle, read
secrets from the environment, make outbound network calls, or write to
disk, entirely independent of whether its trading logic is any good. This
is a gap this ADR exists to close.

## Decision drivers

- The order-authority boundary (ADR-0003) is necessary but not sufficient
  — arbitrary code execution is a distinct risk surface from arbitrary
  order placement.
- Static analysis alone cannot catch everything a determined or buggy
  code generator might produce (obfuscation, dynamic imports) — defence
  in depth is needed, matching the project's existing pattern (R4's two
  independent halt layers, R5's startup balance check).
- The system already has a natural checkpoint before any candidate
  matters: it must pass backtest and walk-forward before promotion is
  even considered (`08-paper-exit-criteria.md` Gate 1). That checkpoint
  is the right place to also enforce code-execution safety, not an
  afterthought bolted on later.
- A human is already in the loop for every capital-relevant decision (R4
  AC4.6, Telegram `/approve` in `04-architecture/conductor.md`) —
  extending that same human checkpoint to cover "a new *version of code*
  is about to run for real" is consistent with the project's existing
  philosophy, not a new one.

## Considered options

- **Candidate code admission: static analysis + sandboxed, network-disabled
  backtest/walk-forward + mandatory human `/approve` before first paper
  entry and every live allocation change** (chosen)
- Static analysis only, no sandbox (rejected — catches only what the
  analysis pattern anticipates, not runtime behaviour)
- Sandbox only, no static analysis (rejected — more expensive to run
  every candidate through a full sandboxed backtest before even a cheap
  first-pass rejection; static analysis is a fast, near-zero-cost first
  filter)
- Run candidates directly in the same environment as everything else,
  relying entirely on ADR-0003's order-authority boundary (rejected —
  this is precisely the gap this ADR exists to close)
- Mandatory human line-by-line code review for every candidate, with no
  automated sandboxing (rejected as the sole control — doesn't scale to a
  nightly loop, and a human reading Python for subtle malicious behaviour
  is a weaker control than automated static analysis plus a
  network-disabled sandbox that makes most bad behaviour harmless even if
  undetected)

## Decision outcome

Chosen option: **candidate code admission**, owned by Conductor, as a
mandatory step before any LLM-generated strategy code is executed
anywhere, even for backtesting:

1. **Static analysis.** Every candidate is scanned before execution.
   Import whitelist enforced; `os`, `subprocess`, `socket`, `requests`
   (and equivalents), and any file-write operation are forbidden and
   cause automatic rejection, logged with the specific violation. No
   candidate that fails static analysis is ever executed, sandboxed or
   not.
2. **Sandboxed backtest/walk-forward.** Candidates that pass static
   analysis run their backtest and walk-forward inside a throwaway,
   network-disabled container — not the live Freqtrade environment, not
   any container with exchange or secret access. The container is
   destroyed after the run regardless of outcome.
3. **Mandatory human `/approve`.** Passing the numeric gates
   (`08-paper-exit-criteria.md` Gate 1: IS Sharpe ≥ 1.0, OOS ≥ 50% of IS,
   etc.) is necessary but not sufficient. A strategy version that
   contains LLM-generated code requires an explicit, logged human
   `/approve` (Telegram, allow-listed operator) before its **first entry
   into the paper stage** — and every subsequent **live allocation
   change** (paper → 25%, 25% → 100%) requires `/approve` again. Numeric
   gates otherwise pass automatically once met; `/approve` is the one
   place a human explicitly reviews before real capital exposure changes.

### Rationale

Static analysis is cheap and catches the obvious cases (an accidental or
malicious `import os` shouldn't need a human to notice). The sandbox is
defence in depth for what static analysis misses — even if a candidate
somehow got network or file access past the import whitelist, a
network-disabled, throwaway container means there is nothing reachable to
exfiltrate to and nothing persistent to have written. The mandatory
`/approve` is the last layer: a human explicitly looks at the fact that
*new code* is about to run for the first time, or capital exposure is
about to change, independent of whether the numeric gates were satisfied
— this resolves the previously-open question in `04-architecture/
conductor.md`'s TBD ("which promotion stages require explicit
`/approve`") with a specific, non-negotiable answer rather than leaving
it to be decided ad hoc in Phase 3.

### Consequences

**Good:**
- Closes the code-execution trust-boundary gap that ADR-0003 alone left
  open — "the LLM never places an order" is necessary but was not, by
  itself, a complete safety story.
- Reuses existing patterns (defence in depth, human-in-the-loop for
  capital changes) rather than inventing a new control philosophy.
- Resolves a previously-open TBD in `04-architecture/conductor.md` with a
  concrete rule.

**Bad / accepted trade-offs:**
- Adds latency to the promotion pipeline (sandbox provisioning, human
  response time for `/approve`) — acceptable given the project's own
  low-turnover, no-rush design posture (research review §5).
- Static-analysis import whitelists can be bypassed by sufficiently
  obfuscated code (e.g. `__import__`, `getattr`-based indirection) — not
  claimed to be airtight; the sandbox and human approval are the layers
  that catch what static analysis misses, not a guarantee that static
  analysis alone is sufficient.
- Requires building and maintaining a sandboxed execution environment
  (Phase 3 work, not yet built) — tracked as a TBD, not deferred
  indefinitely.

## More information

Sandbox runtime implementation (Docker-in-Docker vs. a pre-built,
network-disabled base image) — TBD (Phase 3). Exact static-analysis
tooling (custom AST walker vs. an existing Python sandboxing/linting
library) — TBD (Phase 3). Re-tagged from "Phase 2/3" during Phase 2
closure (work package 2F): this entire admission gate is Conductor/
research-loop scope, which does not exist until Phase 3 — Phase 2's
`Baseline4h` strategy was hand-written, never LLM-generated, so nothing
in Phase 2 exercises this control. See risk register L8 and
`04-architecture/security.md`.
