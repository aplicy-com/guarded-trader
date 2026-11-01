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

## Current status — 2026-10-30: platform complete, no strategy, live trading paused

This section overrides any older "in progress" line below. The phase sections are kept as
written, as history.

**Done: the platform is built and drilled.**
- Freqtrade dry-run on a Hetzner VPS (ADR-0011) with Conductor: ledger, independent risk
  layer, halts, kill switch and nuclear via Telegram, fail-closed boot (ADR-0018), heartbeat
  watchdog, nightly B2 backups, read-only dashboard over Tailscale.
- All six 3A-6 safety drills **passed** on the VPS on 2026-10-05: kill switch, nuclear, restart
  persistence, heartbeat silence, backup + restore, full VPS rebuild
  ([`drills/results-2026-10-04.md`](drills/results-2026-10-04.md)). The records are the
  operator's summaries, not verbatim output.
- The $20 live-pilot package (ADR-0019) is built and gated (`scripts/trading-mode.sh live`).
- A sandboxed research harness: walk-forward, random-entry null, append-only trial registry,
  Deflated Sharpe (ADR-0021).

**Not done: no strategy has passed Gate 1 at real costs.**
- At Kraken Tier-1 cost (0.80 % taker + 0.10 % slippage per side), all four candidates lose money
  over 2022-01 → 2026-10. None beats its random-entry null, and BTC buy-and-hold beats all of
  them ([`research/05-first-candidates.md`](research/05-first-candidates.md)).
- At NDAX's 0.20 % fee, C05 beats its null's Sharpe 95th percentile. It still fails Gate 1
  (IS Sharpe, trade concentration, force-exit share), and at 2× fee, close to NDAX's measured
  spread cost, it loses money again
  ([`research/06-ndax-feasibility.md`](research/06-ndax-feasibility.md)).
- Trial registry: N = 6 registered trials. Every one counts against future DSR.

**Paused: live trading.**
- The $20 pilot has not run. Funding the Kraken account by deposit did not work at first:
  Interac e-Transfer failed, credit card declined, Scotiabank bill payment did not list Kraken.
  An Interac e-Transfer succeeded on 2026-10-31 (CA$35 credited). The funds stay parked on
  Kraken and are not traded.
- NDAX was checked as a replacement venue and **rejected for live**
  ([ADR-0022](05-adr/0022-ndax-rejected-for-live.md)): the key's withdraw scope can't be
  verified through its API, and Freqtrade can't hold stops on the exchange for it.
- The VPS was deleted on 2026-10-31 per
  [`06-runbooks/pause-and-resume.md`](06-runbooks/pause-and-resume.md).
  No exchange API key has been created, so the system has no access to the funds on Kraken.
  The research loop costs nothing while paused (R6).

**Revisit triggers.** Either one reopens the project; neither by itself resumes trading:
1. **Kraken deposits work for this account.** **MET on 2026-10-31.** Then the $20 *plumbing*
   pilot (ADR-0019) can run as designed. It proves the real-exchange path, not an edge: it
   trades a known no-edge strategy and is expected to lose a little.
2. **A candidate passes Gate 1 at real costs.** **Still unmet.** The test is Kraken Tier-1
   taker + slippage, or another venue's verified fee **plus its measured spread**, on a venue
   that passes the same checks ADR-0022 applied (verified no-withdraw key, exchange-held stops).

Resuming means: write down which trigger fired, then follow `pause-and-resume.md` Part B, then
the normal written-plan rule (`CLAUDE.md` §1) before anything touches the live path.

**Status on 2026-10-31:** trigger 1 is met and trigger 2 is unmet, so the project remains
paused. No API key created, no VPS running, no live trading.

**Pause record** (filled in at `pause-and-resume.md` step A10): date stopped: 2026-10-31;
option (power off / server deleted): server deleted; static IP kept: yes, Hetzner Primary IP
retained for reuse (recorded privately);
exchange keys deleted: none existed (no API key was created); off-site backups: B2 retained
(30-day lifecycle); local backup folder: `~/Backups/ai-trading-agent/vps-pause-2026-10-31`.
- 2026-10-31: Kraken Interac e-Transfer deposit succeeded (CA$35 credited). Revisit trigger 1
  ("Kraken deposits work") is met; trigger 2 (Gate 1 at real costs) is unmet, so the project
  remains paused. No API key created, no VPS running. Funds stay parked on Kraken; no live
  trading. Trigger 1 reopened the decision. Decision: remain paused. No plumbing pilot until
  trigger 2 is met.

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

**Entry gate:** Phase 1 exit gate met, **and** Kraken account residency
updated to Canada (Payward Canada) with Interac e-Transfer funding
available — see risk register T3. This must be true before any
live-adjacent setup in this phase (key creation, account configuration);
it is not itself a funding step — principal funding is a deliberate,
explicit Phase 4 action (see Phase 4 entry gate), not something this
phase triggers.

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
  check. (Original plan, as written before Phase 2 began — see the exit
  gate below for what actually resolved this phase vs. what got re-tagged
  to Phase 3/4 during work package 2F's closure pass.)
- Historical OHLCV data pulled for backtesting (Freqtrade `download-data`
  — vs. a paid provider is research review open question §7.3, decide
  here).
- A first, simple strategy candidate (hand-written, not yet LLM-generated)
  running in dry-run, to validate the whole execution path end-to-end
  before Conductor exists.

**Exit gate — actual status as of 2026-09-09 (work package 2F close):**
- [ ] Freqtrade running in Docker, dry-run mode, against real Kraken
      market data, with at least one strategy live in paper mode, for
      **7 consecutive days** (sharpened from the original "at least one
      strategy live" wording to match `docs/phase-2-plan.md` §3's exit
      gate: "Freqtrade dry-run uptime ≥ 7 consecutive days"). **In
      progress** (work package 2D) — started `2026-09-09 17:46 UTC`
      (`make up`, confirmed via `Dry run is enabled` in logs and
      `"dry_run":true` on the REST API's `/show_config`). Expected to lose
      money on paper — the point of this run is host stability and path
      validation, not returns (see `docs/00-vision.md` "What Phase 2
      taught us"). 7-day mark: `2026-09-16 17:46 UTC`. Update this line
      when the uptime bar is actually met — no gaps from the host being
      down count toward it (mirrors the paper-window rule in
      `08-paper-exit-criteria.md`).
- [ ] All built-in protections (StoplossGuard, MaxDrawdown, CooldownPeriod,
      LowProfitPairs) configured with concrete thresholds, not TBDs.
      **3 of 4 done**: `CooldownPeriod`, `StoplossGuard`, `MaxDrawdown` are
      configured with concrete values in `Baseline4h.py`
      (`docs/04-architecture/execution-freqtrade.md`). `LowProfitPairs`
      is deliberately deferred to Phase 2D — it needs real trade history
      to set a meaningful threshold against, which doesn't exist for a
      strategy that has only been backtested so far.
- [ ] Key scoping verified (no withdrawal permission) per
      `docs/06-runbooks/key-rotation.md`. **Not applicable yet — no key
      exists.** Work package 2E (key creation) stays explicitly deferred
      pending Kraken account residency confirmation (risk register T3,
      `docs/phase-2-plan.md` §0); this checkbox cannot be completed before
      2E regardless of anything else in this phase, and that is expected,
      not a gap in this closure pass.
- [x] Secrets hygiene verified: `.gitignore` effective (confirmed);
      gitleaks pre-commit hook installed and active
      (`pre-commit install` run on the trading host, 2026-09-09 — not
      just configured in `.pre-commit-config.yaml`, actually installed
      this time); `pre-commit run gitleaks --all-files` run against the
      full repo and passed clean, 2026-09-09.
- [x] ~~Accountant consulted on tax classification; T1/T3/T4 in the risk
      register updated from Open/TBD to a concrete status.~~ **Re-scoped**
      during this closure pass: the actual consultation is re-tagged to
      block **Phase 4 entry** instead (risk register T1/T4 — Phase 2 is
      dry-run only, zero taxable events exist to consult about yet). What
      Phase 2 *can* deliver — the question list itself
      (`docs/09-tax-questions.md`) — is done. T3 (Kraken registration
      status) is unrelated to tax classification and blocks **2E
      specifically**, not this checkbox.

**Net: Phase 2 exit gate is not yet met.** Two items are genuinely
outstanding — the 7-day dry-run uptime (2D, starting now) and key scoping
(blocked on 2E, itself blocked on external Kraken residency status, not
on anything this repo controls). Protections are 3/4 done by design, not
by omission. Secrets hygiene is fully done. Tax classification was
deliberately moved off this gate entirely, onto Phase 4's.

## Phase 3 — Conductor + research loop + paper trading

**Entry gate:** Phase 2 exit gate met.

**Scope:**
- Conductor service: ledger, promotion-gate engine, risk-limit checker
  (independent second layer for R4), profit-fence job, Telegram bot.
- Nightly research loop wired to Claude, full prompt/response logging.
- `docs/08-paper-exit-criteria.md` finalized with concrete numbers before
  the first strategy is evaluated against them.
- At least one strategy taken through backtest → walk-forward → 3-week
  paper against the finalized exit criteria.
- Sweep destination account/wallet established (no API key issued to the
  running system) and the fence-then-manual-move flow drilled per
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

- [x] **R5 exclusion mechanism** (blocked going live; done for the pilot,
      ADR-0019): `isolation_exclusions` table, `isolation-check` /
      `exclude-balance` CLI, the startup check honouring exclusions, and the
      AC5.4 clearance runbook (`06-runbooks/start-stop.md`, "R5 abort").
- [x] **Fresh live ledger** (blocked going live; done for the pilot, ADR-0019):
      `infra/docker-compose.live.yml` gives the live Conductor its own volume
      and Freqtrade its own trade DB; `scripts/trading-mode.sh` refuses to go
      live over anything but an empty ledger or one with principal 20, and
      archives the dry-run ledger first.
- [ ] Re-record the Freqtrade `/balance` fixture from the live-mode instance
      (the VPS dry-run one shows simulated balances only). Part of the pilot's
      first-day checks (`06-runbooks/go-live-pilot.md`).

### Live pilot ahead of Gate 2 (ADR-0019, decided 2026-10-05)

A **$20** plumbing pilot of `Baseline4h` (a known no-edge strategy) on Kraken,
one position at a time, to validate the real-exchange path. It is **not** a
promotion: it does not count toward Gate 2 or Gate 3, and the remaining **$80
stays undeposited, gated behind Gate 2**.

**Pilot entry gate** (enforced by `scripts/trading-mode.sh live`, which has no
skip flags): a **72-hour clean soak counted from the 2026-10-05 rebuild**
(instead of the 7 days in the 3A exit gate; `infra/live/soak-start`) - no
halt raised by the system since, none active; Kraken key scopes verified from
the VPS (query + create/cancel orders only, IP-whitelisted, no withdraw or
funding); fresh live ledger; dry-run ledger archived; R5 passes against the
real balances. Procedure: [`06-runbooks/go-live-pilot.md`](06-runbooks/go-live-pilot.md).
Not waived: the accountant consultation on tax classification (risk register
T1/T4) is still open and the runbook has the operator acknowledge it before
funding.

**Pilot exit:** judged on plumbing, not P&L - real orders placed/filled/
cancelled and ingested correctly, kill switch and nuclear exercised against the
real exchange, R5 and the loss limits behaved, fees/minimums as predicted. The
write-up goes in `docs/drills/`. Anything beyond $20 needs Gate 2 and a new ADR.

**Scope:**
- Live trading begins at 25% of `max_deployed_capital`, real orders,
  real money.
- ~~Migration to a dedicated mini-PC~~ — superseded: hosting moves to a
  Hetzner VPS in Phase 3 (`docs/05-adr/0011-vps-hosting-on-hetzner.md`);
  `migrate-to-minipc.md` is archived.
- Scale to 100% allocation once the 25% stage is stable — stability
  criteria TBD (Phase 4, to be defined before the 25% stage begins, not
  during it).
- "Planned absence" procedure for the operator (risk register O6).

**Exit gate:**
- [ ] Running at 100% allocation.
- [ ] No breach of R1–R4 at any point during the 25%→100% transition.
- [x] ~~Migration to mini-PC~~ — superseded by ADR-0011 (VPS, Phase 3).
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

Phase 2 (as of work package 2F close, 2026-09-09): resolved this
phase — ~~quote currency~~ (ADR-0008), ~~min order sizes~~
(`docs/research/02-kraken-market-facts.md`), ~~disk encryption~~
(FileVault confirmed On), ~~secret scanning tool~~ (gitleaks, installed
and active), ~~sleep-disable mechanism~~ (Amphetamine,
`infra/README.md`), ~~protection thresholds~~ (3 of 4, see Phase 2 exit
gate above). Genuinely still open: Tailscale (not yet installed — device
action, not blocking Phase 2 exit), dependency automation (re-tagged
Phase 3 — no remote/manifest to point it at yet), Kraken CA registration
status (external, blocks 2E specifically). Tax classification moved off
Phase 2 entirely, re-tagged to block Phase 4 entry (question list ready:
`docs/09-tax-questions.md`). Phase 3: ledger DB engine (resolved early —
~~SQLite~~, ADR-0009), heartbeat interval (resolved 3A-5),
daily/drawdown/consecutive-loss exact thresholds, promotion-approval
stages, backup schedule. Phase 4: mini-PC migration trigger, 25%→100%
stability criteria, planned-absence procedure.
