# 07 — Roadmap

Five phases, each with an explicit entry gate (what must be true to start)
and exit gate (what must be true to move on). No phase starts without a
written, human-approved plan (`CLAUDE.md` §1); no phase's exit gate is
waived silently.

```mermaid
flowchart LR
    P1["Phase 1<br/>Docs scaffold"] --> P2["Phase 2<br/>Infra + Freqtrade<br/>dry-run setup"]
    P2 --> P3["Phase 3<br/>Conductor + research loop<br/>+ paper trading"]
    P3 --> P4["Phase 4<br/>Live: 25% → 100%<br/>allocation"]
    P4 --> P5["Phase 5<br/>Ongoing operation<br/>+ re-validation"]
```

## Phase 1 — Docs scaffold (this phase)

**Entry gate:** research review complete
(`docs/research/01-research-review.md`).

**Scope:** this repository's documentation structure, requirements, risk
register, ADRs, runbooks, licence. No code that connects to an exchange.

**Exit gate:**
- [ ] Every file in the target layout (`docs/phase-1-plan.md` §1) exists
      with real content.
- [ ] R1–R4 reviewed and confirmed by the operator
      (`docs/phase-1-plan.md` §5 checklist).
- [ ] Risk register has nothing the operator disagrees with.
- [ ] Draft paper exit criteria are numbers the operator would actually
      hold the system to.
- [ ] Single conventional commit made, `git init` done, `main` branch.

## Phase 2 — Infra + Freqtrade dry-run setup

**Entry gate:** Phase 1 exit gate met.

**Scope:**
- `infra/` docker-compose for Freqtrade (and a placeholder for Conductor,
  built out in Phase 3).
- Freqtrade configured against Kraken (query+trade-only key), dry-run
  mode only — no live trading in this phase.
- Resolve the Phase-2-tagged TBDs across the docs: Kraken min order
  sizes/fee tiers, quote currency (USD/CAD), disk encryption verification,
  pre-commit secret scanning, Tailscale setup, sleep-disable mechanism,
  dependency-update automation, protection threshold values, accountant
  consultation on tax classification (T1/T3/T4), CRA registration-status
  check.
- Historical OHLCV data pulled for backtesting (Freqtrade `download-data`
  — vs. a paid provider is research review open question §7.3, decide
  here).
- A first, simple strategy candidate (hand-written, not yet LLM-generated)
  running in dry-run, to validate the whole execution path end-to-end
  before Conductor exists.

**Exit gate:**
- [ ] Freqtrade running in Docker, dry-run mode, against real Kraken
      market data, with at least one strategy live in paper mode.
- [ ] All built-in protections (StoplossGuard, MaxDrawdown, CooldownPeriod,
      LowProfitPairs) configured with concrete thresholds, not TBDs.
- [ ] Key scoping verified (no withdrawal permission) per
      `docs/06-runbooks/key-rotation.md`.
- [ ] Secrets hygiene verified: `.gitignore` effective, pre-commit scan
      installed, manual review pass done.
- [ ] Accountant consulted on tax classification; T1/T3/T4 in the risk
      register updated from Open/TBD to a concrete status.

## Phase 3 — Conductor + research loop + paper trading

**Entry gate:** Phase 2 exit gate met.

**Scope:**
- Conductor service: ledger, promotion-gate engine, risk-limit checker
  (independent second layer for R4), profit-sweep job, Telegram bot.
- Nightly research loop wired to Claude, full prompt/response logging.
- `docs/08-paper-exit-criteria.md` finalized with concrete numbers before
  the first strategy is evaluated against them.
- At least one strategy taken through backtest → walk-forward → 3-week
  paper against the finalized exit criteria.
- Sweep destination account/wallet established (no API key issued to the
  running system) and profit-sweep drilled per
  `docs/06-runbooks/profit-sweep.md`.
- Kill switch and nuclear protocol drilled (simulated, in dry-run) per
  their runbooks — not just written, actually exercised.

**Exit gate:**
- [ ] At least one strategy meets every numeric criterion in
      `docs/08-paper-exit-criteria.md`.
- [ ] Zero risk-engine violations, zero unhandled halts across the full
      3-week paper window.
- [ ] Kill switch and nuclear protocol drills completed successfully.
- [ ] Ledger produces a CAD-equivalent, tax-report-ready export (NFR6),
      reviewed with the accountant from Phase 2.
- [ ] Heartbeat/alerting verified working, including the "host down"
      failure mode (independent watchdog).

## Phase 4 — Live: 25% → 100% allocation

**Entry gate:** Phase 3 exit gate met. Explicit, deliberate human decision
to fund the account with the $100 principal (R1) and go live — this is
not an automatic transition.

**Scope:**
- Live trading begins at 25% of `max_deployed_capital`, real orders,
  real money.
- Migration to a dedicated mini-PC per
  `docs/06-runbooks/migrate-to-minipc.md` — trigger condition TBD (see
  `docs/05-adr/0004-mac-first-minipc-later.md`), expected to happen within
  this phase.
- Scale to 100% allocation once the 25% stage is stable — stability
  criteria TBD (Phase 4, to be defined before the 25% stage begins, not
  during it).
- "Planned absence" procedure for the operator (risk register O6).

**Exit gate:**
- [ ] Running at 100% allocation.
- [ ] No breach of R1–R4 at any point during the 25%→100% transition.
- [ ] Migration to mini-PC (or an explicit decision to defer it, with
      reasoning recorded) complete.
- [ ] At least one full re-validation cycle (Phase 5 cadence) completed
      successfully while live.

## Phase 5 — Ongoing operation + re-validation

**Entry gate:** Phase 4 exit gate met.

**Scope:**
- Strategies re-validated every 4–6 weeks (research review §4); demoted
  back to paper on failure, per the promotion pipeline
  (`docs/04-architecture/conductor.md`).
- Regular risk-register review at each cycle.
- Periodic reassessment of framework choice (revisit NautilusTrader once
  its v2 has 2–3 stable releases — research review D5) and of whether
  qanat/vectorbt earn a place in the research sandbox (D6) — neither is on
  the critical path.
- Full, ongoing public reporting of results — win or lose — per
  `docs/00-vision.md` success criteria.

**Exit gate:** N/A — this is the steady state. The project ends (or is
explicitly re-scoped, e.g. principal change, org transfer to Aplicy) by
deliberate decision, not by drift.

## TBD summary

Phase 2: quote currency, min order sizes, disk encryption, secret
scanning tool, Tailscale ACLs, sleep-disable mechanism, dependency
automation, protection thresholds, tax classification, Kraken CA
registration status. Phase 3: ledger DB engine, heartbeat interval,
daily/drawdown/consecutive-loss exact thresholds, promotion-approval
stages, backup schedule. Phase 4: mini-PC migration trigger, 25%→100%
stability criteria, planned-absence procedure.
