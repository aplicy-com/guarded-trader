# Conductor

Python 3.12 / FastAPI service that will own the ledger, capital and risk
rules, the profit fence, the Telegram control surface and (Phase 3B) the
nightly LLM research loop. Design:
[`docs/04-architecture/conductor.md`](../../docs/04-architecture/conductor.md).
It never places, modifies or cancels an exchange order
([ADR-0003](../../docs/05-adr/0003-llm-never-orders.md)).

**Status: 3A-1 skeleton.** Wiring only, no business logic. Ledger and
capital rules are 3A-2, the risk layer 3A-3, Telegram 3A-4, healthchecks and
dashboard 3A-5.

## Layout (`src/conductor/`)

| Layer | Contents | Rule |
|---|---|---|
| `domain/` | `TradingMode`, read-only Freqtrade snapshot dataclasses | Pure: stdlib only, no I/O. `mypy --strict`. |
| `application/` | Ports (`FreqtradeReader`, `Notifier`, `Heartbeat`, `LlmClient`), use cases | Depends on `domain` only. |
| `adapters/` | Freqtrade REST client (**GET-only**), Telegram / healthchecks / LLM stubs | Only place that does I/O to the outside. |
| `infrastructure/` | Settings, SQLite (WAL) engine, scheduler, logging, `/health` | Framework glue. |
| `main.py` | Composition root (`create_app`, `app_factory`) | |

`tests/test_architecture.py` enforces the dependency rules.

## Commands (from the repo root)

    make conductor-test    # pytest
    make conductor-lint    # ruff, ruff format --check, mypy --strict (domain), mypy
    make conductor-shell   # shell in the built image (needs Docker)

Dependencies are exact-pinned in `pyproject.toml` and locked in `uv.lock`;
change them with `uv add` / `uv lock --upgrade-package`.

## Configuration (environment)

Required (startup fails with a clear message if missing/invalid):
`PRINCIPAL_USD` (>0), `DATABASE_URL` (`sqlite:///...` only),
`FREQTRADE__API_SERVER__USERNAME`, `FREQTRADE__API_SERVER__PASSWORD`.
Optional: `TRADING_MODE` (`dry_run` default | `live`), `FREQTRADE_API_URL`
(default `http://freqtrade:8080`), `SCHEDULER_ENABLED`,
`HEARTBEAT_INTERVAL_SECONDS` (default 300, min 30), `LLM_BACKEND`
(`none` | `claude_code_headless` | `anthropic_api`), `LOG_LEVEL`, `LOG_JSON`.

## Runtime

- `GET /health` (internal; no port is published to the host): 200 when the DB
  is in WAL mode and the scheduler is running, else 503. `/docs` and
  `/openapi.json` are disabled.
- The container runs as non-root uid 10001, read-only root filesystem, all
  capabilities dropped, data in the `conductor-data` volume at `/data`.
  Migrations (`alembic upgrade head`) run before the server starts.
- It receives only the env vars listed in `infra/docker-compose.yml`, not the
  whole `.env`: no Kraken keys, no Freqtrade Telegram token.

Test fixtures for the Freqtrade client are described in
`tests/fixtures/freqtrade/README.md` (currently hand-built, not recorded).
