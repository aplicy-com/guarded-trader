# AI Trader (working name)

An open-source, docs-first experiment in running a small ($100), real-money
crypto trading system where a deterministic execution engine does all the
trading and a Claude-driven research loop proposes, tests and reviews
strategies overnight — never the other way around.

## Why

Public evidence on LLMs as live trading decision-makers is not encouraging
(see [`docs/research/01-research-review.md`](docs/research/01-research-review.md)):
every public live-money experiment with an LLM directly choosing trades has
lost money in aggregate. What has worked, at scale, is boring: deterministic
execution, strict risk limits, low turnover, long paper-trading periods, and
treating "AI" as an optimiser or researcher — never the order router.

This project takes that lesson literally. The LLM (Claude) never places,
modifies or cancels an order. It writes and reviews strategy code in a
nightly loop; a deterministic risk engine ([Freqtrade](https://www.freqtrade.io/))
decides whether and how to trade, inside hard limits it cannot be talked out
of.

## What this is

- A real $100 of the author's own money, one-time, never topped up (see
  [`docs/02-requirements.md`](docs/02-requirements.md), R1–R4).
- A fully public research and engineering log: every ADR, every risk, every
  runbook, every requirement — written down before the code that matters
  exists.
- An honest attempt to find out whether a small, disciplined, LLM-assisted
  system can trade without losing the principal, not a claim that it will.

## What this is not

- Not investment advice. Not a signal service. Not a product.
- Not high-frequency or leveraged trading.
- Not a system where the LLM ever touches an exchange key or an order.

## Status

**Phase 1 — Docs scaffold.** No code that connects to an exchange exists yet.
See [`docs/07-roadmap.md`](docs/07-roadmap.md) for the phase plan and
[`docs/phase-1-plan.md`](docs/phase-1-plan.md) for how this scaffold was
generated.

## Quick links

| | |
|---|---|
| Vision & non-goals | [`docs/00-vision.md`](docs/00-vision.md) |
| Research review (the "why" behind every decision) | [`docs/research/01-research-review.md`](docs/research/01-research-review.md) |
| Requirements (R1–R4 + NFRs) | [`docs/02-requirements.md`](docs/02-requirements.md) |
| Risk register | [`docs/03-risk-register.md`](docs/03-risk-register.md) |
| Architecture | [`docs/04-architecture/`](docs/04-architecture/) |
| Decision records (ADRs) | [`docs/05-adr/`](docs/05-adr/) |
| Runbooks | [`docs/06-runbooks/`](docs/06-runbooks/) |
| Roadmap | [`docs/07-roadmap.md`](docs/07-roadmap.md) |
| Paper-trading exit criteria | [`docs/08-paper-exit-criteria.md`](docs/08-paper-exit-criteria.md) |
| Rules for AI-assisted work on this repo | [`CLAUDE.md`](CLAUDE.md) |

## Disclaimer

This is a personal research project, not financial, investment, tax, or
legal advice. Cryptocurrency trading carries a high risk of loss, including
total loss of principal. The author is not a registered financial advisor.
Nothing in this repository, including any strategy, code, or commentary,
should be relied upon as a basis for a real trading decision by anyone other
than the author. Past or backtested performance is not indicative of future
results.

## Licence

Apache License 2.0 — see [`LICENSE`](LICENSE). © 2026 the original author.
