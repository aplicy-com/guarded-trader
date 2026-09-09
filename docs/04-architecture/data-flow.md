# Architecture — Data Flow

Three sequences that matter most: the nightly research loop, a live
trading tick, and a halt. All three are also drilled procedurally in
[`06-runbooks/`](../06-runbooks/).

## 1. Nightly research loop

```mermaid
sequenceDiagram
    participant Sched as Scheduler
    participant Cond as Conductor
    participant Ledger
    participant Claude as Claude API
    participant Gate as Promotion gate
    participant FT as Freqtrade

    Sched->>Cond: trigger nightly run
    Cond->>Ledger: read recent performance, open strategies, past post-mortems
    Cond->>Claude: prompt (context + ask for candidate/review/post-mortem)
    Claude-->>Cond: candidate strategy code / review / analysis
    Cond->>Ledger: log prompt + response + content hash
    Cond->>Gate: submit candidate for backtest
    Gate->>Gate: backtest -> walk-forward (deterministic, no LLM)
    alt passes
        Gate->>Ledger: record pass, queue for paper stage
        Gate->>FT: (at next safe window) point dry-run at new strategy version
    else fails
        Gate->>Ledger: record rejection + reason
    end
    Cond->>Cond: heartbeat emitted
```

Note: the LLM's output never reaches Freqtrade directly. It reaches the
Gate, which is deterministic code, and only a *pass* results in Freqtrade
being reconfigured — and only in dry-run at that point.

## 2. Live tick (bar close to ledger update)

```mermaid
sequenceDiagram
    participant Kraken
    participant FT as Freqtrade (live)
    participant Cond as Conductor
    participant Ledger

    Kraken-->>FT: OHLCV bar close (4h/1d)
    FT->>FT: evaluate pinned strategy signal
    FT->>FT: check protections (StoplossGuard, MaxDrawdown, CooldownPeriod)
    alt protections clear AND no active halt
        FT->>Kraken: place order (maker-preferred)
        Kraken-->>FT: fill confirmation
        FT->>Cond: fill event (via REST/webhook)
        Cond->>Ledger: record fill, update working profit, recompute max_deployed_capital
        Cond->>Cond: re-check R4 limits independently (second layer)
    else protections trip OR halt active
        FT->>FT: no new order placed
        FT->>Cond: protection-trip event
        Cond->>Ledger: record event
        Cond->>Cond: alert operator (Telegram)
    end
```

## 3. Halt (trigger to human re-enable)

```mermaid
sequenceDiagram
    participant Trigger as Trigger source<br/>(Freqtrade protection OR<br/>Conductor risk-check OR<br/>operator command)
    participant Cond as Conductor
    participant FT as Freqtrade
    participant Ledger
    participant TG as Telegram
    participant Op as Operator

    Trigger->>Cond: halt condition detected
    Cond->>Ledger: persist halt state (type, reason, timestamp)
    Cond->>FT: block new order entry (kill switch)
    opt nuclear protocol (data loss / exchange anomaly)
        Cond->>FT: cancel open orders, flatten where safe
    end
    Cond->>TG: alert operator (halt type, reason, current state)
    TG-->>Op: notification
    Note over Op: no time pressure — halt is safe-by-default
    Op->>TG: /resume <halt-type> (when ready, after review)
    TG->>Cond: authenticated resume command
    Cond->>Ledger: record resume with operator identity + timestamp
    Cond->>FT: unblock new order entry
```

The critical property in all three diagrams: **the ledger is written
before or alongside the action it describes**, never after, so a crash
mid-sequence cannot leave the system in an undocumented state — see AC4.5.

## TBD

- Exact webhook vs. polling mechanism between Freqtrade and Conductor for
  fill events — TBD (Phase 3), re-tagged from "Phase 2/3" during Phase 2
  closure (Conductor is the consumer here and doesn't exist until Phase
  3; Freqtrade's REST API itself is already up in Phase 2, see
  `infra/README.md`), likely Freqtrade's REST API polled on a short
  interval plus its optional webhook feature.
- Retry/backoff behaviour for the Telegram alert path if Telegram itself
  is unreachable — TBD (Phase 3), candidate fallback: email or a second
  channel.
