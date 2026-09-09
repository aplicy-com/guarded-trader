# ADR-0001: Use Freqtrade as the execution and base risk engine

## Status

Accepted — 2026-09-09

## Context and problem statement

We need something to actually place, size, and protect orders on Kraken.
Building this from scratch is both risky (order-management bugs are the
kind of bug that loses real money — see the Knight Capital reference case)
and unnecessary — mature open-source options exist. Which one do we build
on?

## Decision drivers

- Must support Kraken (spot).
- Must have a paper-trading mode that exercises the *same* code path as
  live trading, so our 3-week paper gate actually validates what will run
  live.
- Must have built-in, configurable risk protections (stoploss guard,
  drawdown halt, cooldown) as an independent second layer beneath our own
  Conductor checks.
- Strategy code should be something an LLM can generate, test, and diff
  (i.e. plain Python), since strategies are proposed by Claude in the
  nightly research loop.
- Must be mature enough to trust with real money at the time we adopt it.

## Considered options

- **Freqtrade**
- **NautilusTrader**
- **Hummingbot**
- **qanat**
- Build our own minimal order-management layer

## Decision outcome

Chosen option: **Freqtrade**, run in Docker as a separate service, driven
by our own Conductor layer. Full comparison in
[`../research/01-research-review.md`](../research/01-research-review.md)
§2.

### Rationale

- Dry-run mode is exactly our 3-week paper gate with zero code change
  between paper and live.
- Strategies are Python classes — directly generatable, testable, and
  diffable by an LLM-driven research loop.
- Ships `StoplossGuard`, `MaxDrawdown`, `CooldownPeriod`, and
  `LowProfitPairs` protections out of the box — a second, independent risk
  layer beneath Conductor's own checks (R4 AC4.4).
- Telegram + REST API give us remote control and monitoring from day one.
- Mature (since 2017, active monthly releases), Kraken-supported via CCXT.
- GPL-3 licence is acceptable because Freqtrade runs as a separate Docker
  service, communicated with only via its REST API — this repository is
  not a derivative work and stays Apache-2.0 (see
  [`0006-apache-2-licence.md`](0006-apache-2-licence.md)).

### Consequences

**Good:**
- Fastest credible path to a safe paper-trading gate.
- Battle-tested order-management code we don't have to write or debug
  under live-money pressure.
- Protections give defence-in-depth for R4 essentially for free.

**Bad / accepted trade-offs:**
- Coupled to Freqtrade's architecture and Python; a future move to a
  different engine (e.g. NautilusTrader once v2 stabilises) would require
  a strategy-code migration.
- GPL-3 means Freqtrade's own code cannot be vendored/modified in-repo
  under our Apache-2.0 licence without care — we treat it as an external
  service, not a library.
- Not built for high-frequency or complex multi-venue execution — acceptable
  because [`0005-low-frequency-only.md`](0005-low-frequency-only.md) rules
  that out anyway.

## More information

Revisit NautilusTrader once its v2 has had 2–3 stable releases (research
review D5) — tracked as a future ADR candidate, not an action item now.
