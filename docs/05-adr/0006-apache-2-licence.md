# ADR-0006: Apache License 2.0, copyright the original author

## Status

Accepted — 2026-09-09

## Context and problem statement

This repository is intended to be open-source-ready from day one
(`00-vision.md`), currently owned personally by the operator with a stated
possibility of later transfer to an organization (Aplicy) if the project
succeeds (`docs/phase-1-plan.md` header). What licence should the repo
carry, and whose copyright?

## Decision drivers

- Must be a widely recognised, permissive open-source licence — this is a
  personal research project meant to be freely readable/forkable, not a
  commercial product with restrictive terms.
- Must include an explicit patent grant, given the project may eventually
  involve novel strategy/risk-engine logic worth protecting against
  patent trolling of derivative works.
- Must be easy to reassign or relicense later if the project transfers to
  an organization (Aplicy) — a personal copyright holder with a standard,
  well-understood licence is the simplest starting point for that.
- Must be compatible with depending on Freqtrade (GPL-3) as an external
  service rather than a vendored library — see
  [`0001-freqtrade.md`](0001-freqtrade.md) consequences.

## Considered options

- **Apache License 2.0**
- MIT License
- GPL-3 (matching Freqtrade)
- Proprietary / all-rights-reserved (not open-source)

## Decision outcome

Chosen option: **Apache License 2.0**, copyright 2026 the original author.
See [`../../LICENSE`](../../LICENSE).

### Rationale

- Explicit patent grant and patent-litigation retaliation clause, which
  MIT lacks — relevant given this repo will eventually contain strategy
  and risk-engine logic.
- Permissive (no copyleft obligation), unlike GPL-3 — keeps this repo's
  licence independent of Freqtrade's, consistent with treating Freqtrade
  as an external service (`0001-freqtrade.md`).
- Extremely well understood by both individual contributors and any future
  organizational owner (Aplicy) — no unusual terms to explain.
- Personal copyright (the original author) is simple to reassign later: a
  copyright/licence header change plus a NOTICE update if/when the project
  transfers, without needing a contributor licence agreement process at
  this stage (project has one contributor: the operator).

### Consequences

**Good:**
- Repo can be made public at any point without a licensing decision
  blocking that.
- No conflict with running Freqtrade (GPL-3) as a separate service.
- Straightforward path to reassigning copyright to Aplicy later if the
  project is transferred, per the stated intent in `docs/phase-1-plan.md`.

**Bad / accepted trade-offs:**
- Permissive licensing means anyone can fork and use the strategy/risk
  logic commercially without reciprocation — accepted, consistent with
  this being a transparent research project, not a product.
- If the project transfers to Aplicy, existing distributed copies retain
  the original copyright notice for their version — normal Apache-2.0
  behaviour, not a defect, but worth knowing in advance.

## More information

If the project transfers ownership to Aplicy, this ADR should be updated
(new ADR, not an edit) with the new copyright holder and any NOTICE file
changes, rather than silently changing `LICENSE`.
