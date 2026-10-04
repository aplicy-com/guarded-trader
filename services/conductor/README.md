# Conductor

Python 3.12 / FastAPI service that will own the ledger, capital and risk
rules, the profit fence, the Telegram control surface and (Phase 3B) the
nightly LLM research loop. Design:
[`docs/04-architecture/conductor.md`](../../docs/04-architecture/conductor.md).
It never places, modifies or cancels an exchange order
([ADR-0003](../../docs/05-adr/0003-llm-never-orders.md)).

**Status: 3A-2 ledger + capital rules.** The ledger, read-only ingest, R1
principal, R2 capital *computation*, R3 fence, R5 startup check and NFR6 CAD
export are implemented. **Nothing is enforced yet**: Conductor stays strictly
read-only toward Freqtrade (GET only); enforcement of `max_deployed_capital`
and the risk layer are 3A-3, Telegram alerts 3A-4, healthchecks and dashboard
3A-5.

## What it does (3A-2)

- **Ledger** (SQLite/WAL, Alembic `0002_ledger`): `principal`, `trades`
  (unique per Freqtrade instance + trade id), `equity_snapshots`,
  `fence_events`, `manual_transfers`, `audit_log`, `fx_rates`,
  `trade_cad_valuations`. Money is `Decimal` stored as exact decimal **TEXT**
  (SQLite's NUMERIC affinity would round-trip through binary float), timestamps
  are UTC ISO-8601. `principal`, `fence_events`, `manual_transfers` and
  `audit_log` are append-only: database triggers abort any UPDATE/DELETE.
- **Ingest** (every `INGEST_INTERVAL_SECONDS`, default 300): reads `/status` and
  `/trades` from each Freqtrade instance and upserts idempotently. A closed
  trade is final; an unreachable instance never blocks the others.
- **R1**: the principal is recorded once from `PRINCIPAL_USD`. A later mismatch
  alerts, audits and **refuses to start** (exit 1); it is never overwritten.
- **R2** (compute only): `max_deployed_capital = principal + working_profit`
  (floored at 0) where `working_profit = realized_profit - fenced_total`. Shown
  on the internal `GET /capital` (`"enforced": false`) and `cli capital`.
- **R3**: a daily UTC fence job (00:05 UTC, plus a catch-up run on every start)
  fences working profit above `DAILY_PROFIT_CAP_USD`. Ledger-only: no exchange
  call. The cap's value is **TBD (Phase 3)**, so unset means nothing is fenced
  (warning logged). Missed days and "manual move due" (unmoved >=
  `MANUAL_MOVE_THRESHOLD_USD`, or 30 days since the last move) are logged
  (alerts are 3A-4).
- **R5**: in `TRADING_MODE=live` the startup gate ingests, then compares the
  exchange balance of every whitelisted base asset with what the ledger's own
  open positions account for; any unexplained excess, or any failure to check,
  refuses to start. In `dry_run` it is a logged no-op.
- **NFR6**: closed trades are valued in CAD (cost at the open-day rate, net
  proceeds at the close-day rate) from the Bank of Canada Valet `FXUSDCAD`
  daily series, cached in the DB, once the close day (UTC) has ended. Weekends
  and holidays use the previous published rate. Fair values only: no tax
  treatment is assumed (`docs/09-tax-questions.md`).

## Operator CLI (inside the container)

    docker compose --env-file .env -f infra/docker-compose.yml exec conductor \
      python -m conductor.cli <command>

    capital                       print the R2 figures
    record-transfer --amount ...  record a manual transfer already made on Kraken
    value-trades                  fetch BoC rates and value closed trades now
    export-tax [--out FILE]       CSV of valued closed trades (stdout by default)

## Layout (`src/conductor/`)

| Layer | Contents | Rule |
|---|---|---|
| `domain/` | `TradingMode`, Freqtrade snapshot dataclasses, capital / fence / isolation / tax rules | Pure: stdlib only, no I/O. `mypy --strict`. |
| `application/` | Ports (`FreqtradeReader`, `Ledger`, `FxRateProvider`, `Notifier`, ...), use cases | Depends on `domain` (and the `structlog` logging facade) only. |
| `adapters/` | Freqtrade REST client (**GET-only**), Bank of Canada FX, Telegram / healthchecks / LLM stubs | Only place that does I/O to the outside. |
| `infrastructure/` | Settings, SQLite (WAL) engine, ledger schema + repository, scheduler, logging, `/health`, `/capital` | Framework glue. |
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
Optional: `DAILY_PROFIT_CAP_USD` (blank = unset, TBD Phase 3),
`MANUAL_MOVE_THRESHOLD_USD` (default 25), `INGEST_INTERVAL_SECONDS` (default
300, min 30), `FREQTRADE_INSTANCE_NAME` (ledger label, default `primary`),
`TRADING_MODE` (`dry_run` default | `live`), `FREQTRADE_API_URL`
(default `http://freqtrade:8080`), `SCHEDULER_ENABLED`,
`HEARTBEAT_INTERVAL_SECONDS` (default 300, min 30), `LLM_BACKEND`
(`none` | `claude_code_headless` | `anthropic_api`), `LOG_LEVEL`, `LOG_JSON`.

## Runtime

- `GET /capital` (internal): R2 figures as strings; compute only.
- `GET /health` (internal; no port is published to the host): 200 when the DB
  is in WAL mode and the scheduler is running, else 503. `/docs` and
  `/openapi.json` are disabled.
- The container runs as non-root uid 10001, read-only root filesystem, all
  capabilities dropped, data in the `conductor-data` volume at `/data`.
  Migrations (`alembic upgrade head`) run before the server starts.
- It receives only the env vars listed in `infra/docker-compose.yml`, not the
  whole `.env`: no Kraken keys, no Freqtrade Telegram token.

Test fixtures: `tests/fixtures/freqtrade/README.md` (recorded from a real
dry-run instance, except `status_empty`, `balance` and `whitelist`, which are
hand-built) and `tests/fixtures/boc/README.md` (recorded from the Bank of Canada).
