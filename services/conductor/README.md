# Conductor

**Status: placeholder — implementation starts Phase 3.**

Conductor is the Python/FastAPI service that owns the nightly LLM research
loop, the ledger, the promotion-gate engine, the profit-sweep job, the
risk-limit checker (the second, independent layer for R4), and the
Telegram control surface. It is the only part of this system that talks to
Claude, and the only part that talks to the sweep destination — it never
places, modifies, or cancels an exchange order itself (that's Freqtrade's
job, and only Freqtrade's — see
[`../../docs/05-adr/0003-llm-never-orders.md`](../../docs/05-adr/0003-llm-never-orders.md)).

Design is documented ahead of code in
[`../../docs/04-architecture/conductor.md`](../../docs/04-architecture/conductor.md).
Nothing in this directory connects to an exchange; do not add anything
here that does before Phase 3's plan is written and approved
(`CLAUDE.md` §1).

## Planned contents (Phase 3)

- `api/` — FastAPI app: REST endpoints backing `/status` and health
  checks.
- `research_loop/` — nightly Claude-driven candidate generation, logged
  with prompt/response hashes.
- `gate/` — deterministic backtest/walk-forward/paper/allocation
  promotion logic.
- `risk/` — independent daily-loss/drawdown/consecutive-loss checker.
- `sweep/` — daily profit-sweep job.
- `telegram/` — bot command handling, chat-ID allowlist auth.
- `ledger/` — DB models and access layer (engine TBD, see architecture
  doc).

See the [roadmap](../../docs/07-roadmap.md) Phase 3 entry/exit gates
before starting implementation here.
