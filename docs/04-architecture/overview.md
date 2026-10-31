# Architecture — Overview

Two independent services, one deterministic and money-moving, one advisory
and read/propose-only, connected through a ledger both can read but only
Conductor writes decisions to.

## Context diagram

```mermaid
flowchart TB
    Operator["Operator"]
    Claude["Claude API<br/>(research/review only)"]
    Kraken["Kraken exchange"]
    Telegram["Telegram"]
    SweepAcct["Sweep destination<br/>account/wallet<br/>(no API key held by system)"]

    subgraph System["Guarded Trader system"]
        Conductor["Conductor<br/>(research loop, ledger, gates, kill switch)"]
        Freqtrade["Freqtrade<br/>(execution + risk engine)"]
    end

    Operator -- "commands: kill switch, flatten,<br/>re-enable, approve promotion" --> Telegram
    Telegram <--> Conductor
    Conductor -- "nightly research prompts" --> Claude
    Claude -- "candidate strategy code,<br/>reviews, post-mortems" --> Conductor
    Conductor -- "promoted strategy version,<br/>risk config, halt/resume" --> Freqtrade
    Freqtrade -- "fills, balances, order state" --> Conductor
    Freqtrade -- "orders (query/trade only key)" <--> Kraken
    Operator -- "manual transfer via Kraken's own UI,<br/>triggered by threshold/monthly alert" --> SweepAcct
    Conductor -- "alerts: halts, errors,<br/>fencing/move-due, backup failures" --> Telegram
    Conductor -- "heartbeat ping (only while healthy);<br/>silence alerts the operator" --> Healthchecks["healthchecks.io"]
    Conductor -- "nightly DB backups<br/>(write-only key)" --> B2["Backblaze B2"]
```

**Key invariant visible in this diagram:** Claude has no arrow to Kraken,
directly or indirectly through Freqtrade. Every arrow from Claude terminates
at Conductor, which treats it as a proposal, not a command. See
[`ADR-0003`](../05-adr/0003-llm-never-orders.md). A second invariant:
Conductor has no arrow to the sweep destination either — profit fencing is
a ledger-only operation inside Conductor, and the only path to the sweep
destination is the Operator acting manually via Kraken's own interface
(R3).

## Container diagram

```mermaid
flowchart TB
    subgraph Host["Trading host (Hetzner VPS, Tailscale-only — see ADR-0011; Mac during Phase 2)"]
        subgraph ConductorSvc["Conductor service (Python/FastAPI, Docker)"]
            API["REST API"]
            Ingest["Fill/state ingestion<br/>(polls Freqtrade, writes Ledger)"]
            Loop["Nightly research-loop worker"]
            Admission["Candidate code admission<br/>(static analysis +<br/>sandboxed, no-network backtest/WF — ADR-0007)"]
            Gate["Promotion-gate engine<br/>(numeric gates, /approve routing,<br/>paper→25%→100%)"]
            RiskCheck["Risk-limit checker<br/>(R4: daily/drawdown/consec-loss)"]
            Fence["Profit-fence job"]
            Bot["Telegram bot handler"]
        end

        subgraph FreqtradeSvc["Freqtrade service (Docker)"]
            Strategy["Pinned strategy code<br/>(git commit hash)"]
            Protections["Built-in protections<br/>(StoplossGuard, MaxDrawdown,<br/>CooldownPeriod, LowProfitPairs)"]
            REST["Freqtrade REST API"]
        end

        Ledger[("Ledger DB<br/>(SQLite WAL — ADR-0009)")]
    end

    API --> Ledger
    REST -- "fills, balances,<br/>order state (polled)" --> Ingest
    Ingest --> Ledger
    Loop --> Admission
    Admission --> Gate
    Gate -- "promote/demote strategy<br/>(after /approve where required)" --> REST
    Bot -- "/approve routing" --> Gate
    RiskCheck -- "halt / resume" --> REST
    RiskCheck --> Ledger
    Fence --> Ledger
    Bot --> RiskCheck
    Bot --> Fence
    REST --> Protections
    Protections --> Strategy
```

## Design principles

1. **Two trust domains.** Anything Claude produces is a *proposal* that
   lives in the LLM/research domain until it passes deterministic gates
   into the execution domain. No code path collapses this boundary — and
   this covers the *code itself*, not just the trading decision it
   encodes: LLM-generated strategy code passes static analysis and runs
   only inside a throwaway, network-disabled sandbox (candidate code
   admission, [`ADR-0007`](../05-adr/0007-candidate-code-admission.md))
   before it is ever considered for even paper trading, let alone live
   capital.
2. **The execution domain is boring on purpose.** Freqtrade's protections
   and its dry-run/live code-path parity are load-bearing — see
   [`execution-freqtrade.md`](execution-freqtrade.md).
3. **Every money-relevant fact lives in the ledger**, not in memory or in
   an LLM's context window, and **only Conductor ever writes to it** —
   Freqtrade is polled for fills/state via its REST API and never given
   ledger write access, so there is exactly one writer to reconcile
   against. Restarting any service must never lose halt state, principal
   record, or promotion stage.
4. **Fail closed.** Any ambiguity (a missed fencing run, reconciliation
   mismatch, heartbeat silence) defaults to halting or blocking new risk,
   never to proceeding optimistically.

## Related documents

- [`conductor.md`](conductor.md) — research loop, ledger, gates, kill
  switch, Telegram in detail.
- [`execution-freqtrade.md`](execution-freqtrade.md) — Freqtrade
  configuration and dry-run/live handling.
- [`data-flow.md`](data-flow.md) — sequence diagrams for the nightly loop,
  a live tick, and a halt.
- [`security.md`](security.md) — key scopes, secrets, network.

## TBD

- ~~Ledger DB engine (Postgres assumed; SQLite may suffice at this
  scale)~~ — resolved: SQLite, see
  [`ADR-0009`](../05-adr/0009-sqlite-ledger.md).
- Exact container orchestration (`docker compose` assumed for Phase 1–4
  scale; no Kubernetes planned) — confirmed direction, formalized in
  [`infra/README.md`](../../infra/README.md) at Phase 2.
- Sandboxed runtime for candidate code admission (Docker-in-Docker vs. a
  pre-built, network-disabled base image) — TBD (Phase 3), re-tagged from
  "Phase 2/3" during Phase 2 closure (Conductor doesn't exist until Phase
  3), see
  [`ADR-0007`](../05-adr/0007-candidate-code-admission.md).
