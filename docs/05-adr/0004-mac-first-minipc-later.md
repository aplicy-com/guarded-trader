# ADR-0004: Run on the Mac first; migrate to a dedicated mini-PC later

## Status

Accepted — 2026-09-09

## Context and problem statement

The trading stack (Conductor + Freqtrade, Docker) needs a host that is
awake and reachable continuously — a missed heartbeat or a sleeping host
while a position is open is itself a risk (risk register O1). The
operator's Mac is available immediately; a dedicated always-on mini-PC is
not yet provisioned. Where do we run Phase 1–4?

## Decision drivers

- Time-to-first-paper-run: provisioning and hardening a new mini-PC is
  extra Phase 2 work we don't need to block on.
- Reliability: a laptop that can sleep, get closed, travel, or be used for
  unrelated work is a worse long-term host than dedicated, always-on
  hardware.
- Cost: no need to buy hardware before the system has even passed a
  backtest, let alone gone live.
- The research review's open question §7.2 explicitly leaves "Mac vs.
  mini-PC from day one" open — this ADR resolves it for Phase 1–4 and
  defers the final-state answer.

## Considered options

- **Mac first (Phase 1–4), migrate to a dedicated mini-PC once the system
  is validated (Phase 4/5)**
- Mini-PC from day one
- Cloud VM from day one

## Decision outcome

Chosen option: **Mac first, migrate to a mini-PC once the system has
cleared the paper stage and is running live** (exact trigger point TBD —
see below). Rationale: get to a working paper-trading loop fastest, with
the operator's own hardware, while explicitly tracking the sleep/power
risk (O1) with mitigations (`caffeinate`/sleep-disable, heartbeat
monitoring) rather than pretending it doesn't exist. Migrate once the
operational cost of an unreliable host (real money live) exceeds the
convenience of using existing hardware.

A cloud VM was considered and rejected for now: it removes the
sleep/power problem but introduces a new one — a third-party host with
network access to exchange-adjacent secrets, and recurring cost, before
the system has proven anything. Revisit if the mini-PC migration proves
harder than expected.

### Consequences

**Good:**
- No hardware purchase or provisioning blocks Phase 1–4.
- Forces the sleep/power/heartbeat risk (O1) to be solved with monitoring
  and config rather than assumed away by "the hardware is always on" —
  makes the eventual mini-PC migration a reliability upgrade, not a
  first-time fix for a previously-ignored risk.

**Bad / accepted trade-offs:**
- The Mac is a shared-use machine; discipline is required to keep it
  awake and undisturbed while the stack is running (see
  `06-runbooks/start-stop.md`).
- A migration effort (`06-runbooks/migrate-to-minipc.md`) is now a known
  future task rather than a one-time setup.

## More information

**TBD (Phase 4):** exact trigger condition for migrating (e.g. "first live
allocation reaches 100%", "N weeks of stable paper trading", or a fixed
calendar point) — deliberately not fixed at Phase 1 since it depends on
how Phase 3 paper trading actually goes.
