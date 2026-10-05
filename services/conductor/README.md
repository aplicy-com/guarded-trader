# Conductor

Python 3.12 / FastAPI service that will own the ledger, capital and risk
rules, the profit fence, the Telegram control surface and (Phase 3B) the
nightly LLM research loop. Design:
[`docs/04-architecture/conductor.md`](../../docs/04-architecture/conductor.md).
It never places an exchange order itself, and no LLM code can reach its Freqtrade
write client ([ADR-0003](../../docs/05-adr/0003-llm-never-orders.md),
[ADR-0014](../../docs/05-adr/0014-conductor-write-surface-and-halt-state.md)).

**Status: 3A-4 Telegram.** (3A-3 risk layer below it.) (3A-2 below, plus the halt/enforcement features
in "Risk layer".) Conductor now has a *minimal, allowlisted* write surface
toward Freqtrade (ADR-0014). The 3A-2 ledger, read-only ingest, R1
principal, R2 capital *computation*, R3 fence, R5 startup check and NFR6 CAD
export are implemented. Telegram alerts are 3A-4, healthchecks and dashboard
3A-5.

## Risk layer (3A-3)

Every `RISK_CHECK_INTERVAL_SECONDS` (60) the risk cycle ingests, evaluates the
limits **from the ledger**, persists a halt for any breach and re-applies
active halts to Freqtrade:

- R4: daily loss (3% of trading capital, realized + unrealized), max drawdown
  from peak equity (10%), consecutive losses (3, per Freqtrade instance).
- R2: open exposure above `max_deployed_capital`.
- R7: more than `MAX_CONCURRENT_POSITIONS` (2) open positions: the whole
  whitelist is one exposure group (ADR-0013). Keep it equal to `max_open_trades`.
- A halt blocks entries (Freqtrade `stopentry`), is stored in `halts` (append-only),
  survives restarts, and is re-sent whenever Freqtrade is seen "running" (e.g.
  after its own restart). Only `clear-halt` with a named operator resumes. If
  Freqtrade is unreachable the failure is logged and retried; startup is never
  blocked by it.
- The write client allows only: `stopentry`, `start`, `stop`, `forceexit` (all, market),
  cancel one trade's open order. See `adapters/freqtrade/control_client.py`.
- **Not done:** auto-flatten on drawdown (AC4.2) and writing `available_capital`
  to Freqtrade (R2 is enforced by pausing entries only).

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
  call. `.env.example` ships `DAILY_PROFIT_CAP_USD=10` (a working default; the
  final value is still to be ratified, Phase 3). The code itself has no default:
  unset or blank means nothing is fenced (warning logged). Missed days and "manual move due" (unmoved >=
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
    halts [--all]                 list active (or all) halts
    kill --operator NAME          kill switch: pause new entries on every instance
    nuclear --operator NAME --confirm-flatten-everything
                                  cancel orders, market-exit all, stop
    clear-halt ID --operator NAME [--note ...]   the only way to resume
    export-tax [--out FILE]       CSV of valued closed trades (stdout by default)

## Layout (`src/conductor/`)

| Layer | Contents | Rule |
|---|---|---|
| `domain/` | `TradingMode`, Freqtrade snapshot dataclasses, capital / fence / isolation / tax rules | Pure: stdlib only, no I/O. `mypy --strict`. |
| `application/` | Ports (`FreqtradeReader`, `Ledger`, `FxRateProvider`, `Notifier`, ...), use cases | Depends on `domain` (and the `structlog` logging facade) only. |
| `adapters/` | Freqtrade REST client (**GET-only**) and write client (allowlisted), Bank of Canada FX, Telegram alerts + polling bot, healthchecks / LLM stubs | Only place that does I/O to the outside. |
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
Optional: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_CHAT_IDS` (both or neither),
`TELEGRAM_COMMANDS_ENABLED` (true), `DAILY_LOSS_LIMIT_PCT` (3), `MAX_DRAWDOWN_PCT` (10),
`CONSECUTIVE_LOSS_LIMIT` (3), `MAX_CONCURRENT_POSITIONS` (2),
`RISK_CHECK_INTERVAL_SECONDS` (60, min 15), `DAILY_PROFIT_CAP_USD` (no code default; `.env.example` sets 10; blank = unset),
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
