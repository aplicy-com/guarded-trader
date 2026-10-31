# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0.0, any minor version may change behaviour.

Not financial advice: a version number says nothing about a trading edge. None of these
releases contains a strategy that passes the project's own Gate 1.

## [Unreleased]

## [0.1.0] - TBD (set when the tag is pushed)

The first public release: the platform as built and drilled from September to October 2026,
with live trading paused and every research result published.
[Release notes](docs/releases/v0.1.0.md).

### Added

- **Execution**: Freqtrade (unmodified upstream image) in dry-run by default, 4h/1d bars
  only, at most 2 open trades, protections in the strategy (ADR-0001, ADR-0005).
- **Conductor** (`services/conductor/`), the safety service beside Freqtrade:
  - USD ledger with principal, working profit, profit fencing and per-trade CAD export for
    tax records (R1–R3, ADR-0008, ADR-0009, ADR-0012);
  - an independent risk layer: daily-loss, drawdown, consecutive-loss, capital-exceeded and
    correlation-guard halts, each cleared only by a human (R2, R4, R7, ADR-0013, ADR-0014);
  - kill switch and nuclear flatten, through an allowlisted Freqtrade write client;
  - fail-closed boot: Freqtrade always starts paused, Conductor starts it only with no active
    halt (ADR-0018);
  - account isolation: refuses to start rather than trade coins it didn't buy (R5);
  - Telegram commands with a `yes <code>` confirmation within 60 s for every write, and
    alerts (ADR-0015);
  - health-gated heartbeat to healthchecks.io, nightly backups to Backblaze B2 with a
    write-only key (ADR-0016), and a read-only dashboard (ADR-0017).
- **Research harness** (`services/research/`): sandboxed (no network, read-only, CPU, memory
  and time capped) walk-forward backtests, random-entry null, Deflated Sharpe and an
  append-only trial registry; one cost configuration at Kraken Tier-1 taker plus slippage for
  every backtest (ADR-0020, ADR-0021).
- **Data**: verification and conversion of Kraken's official OHLCVT archive (ADR-0020).
- **Infrastructure**: Terraform for a Hetzner VPS reachable only over Tailscale, host
  hardening, and Make targets for deploy, lockdown checks and remote logs (ADR-0011).
- **Live-pilot package** for $20 of plumbing tests, built and gated but never run (ADR-0019).
- **Key checks**: behavioural scope checks for exchange keys run from the server; venues whose
  keys can't be shown unable to withdraw are rejected (ADR-0022).
- **Documentation**: vision, requirements R1–R7, risk register, architecture, 23 ADRs,
  runbooks (provisioning, rebuild, restore, go-live, pause and resume), drill procedures and
  results, research reports, and an accountant question list.
- **Project**: Apache-2.0 under Aplicy Inc. with NOTICE (ADR-0023), CONTRIBUTING with DCO,
  SECURITY, Code of Conduct, issue and PR templates, CI (tests, lint, gitleaks history scan),
  README images and their generators (`scripts/docs_assets/`).

### Fixed

- The dashboard's equity chart never drew a line: Chart.js got `Date` objects with
  `parsing: false`, so the x-axis collapsed. It now uses epoch milliseconds over a fixed
  30-day window.

### Results recorded

- Four registered candidates, 2022-01 → 2026-10 at Kraken Tier-1 cost: all lose money, none
  beats its random-entry null, BTC buy-and-hold beats all of them
  ([report](docs/research/05-first-candidates.md)).
- At a 0.20 % fee, C05 beats its null but still fails Gate 1
  ([report](docs/research/06-ndax-feasibility.md)).
- All six safety drills passed on the VPS on 2026-10-05 ([results](docs/drills/results-2026-10-04.md)).

[Unreleased]: https://github.com/aplicy-com/guarded-trader/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aplicy-com/guarded-trader/releases/tag/v0.1.0
