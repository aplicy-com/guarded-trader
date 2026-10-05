# Infra

Work package 2A (`docs/phase-2-plan.md`) — Freqtrade running in Docker,
dry-run only. Conductor and the ledger DB are added in Phase 3; this
compose file runs Freqtrade alone. See
[`../docs/04-architecture/overview.md`](../docs/04-architecture/overview.md)
for the target container diagram and
[`../docs/04-architecture/execution-freqtrade.md`](../docs/04-architecture/execution-freqtrade.md)
for why Freqtrade is configured the way it is.

## Where this runs

From Phase 3 the stack runs on a Hetzner VPS reachable only over Tailscale
([ADR-0011](../docs/05-adr/0011-vps-hosting-on-hetzner.md)); the Mac is
dev-only. Provisioning code is in [`terraform/`](terraform/), and the
procedures are
[`provision-vps.md`](../docs/06-runbooks/provision-vps.md) and
[`rebuild-vps.md`](../docs/06-runbooks/rebuild-vps.md). Remote targets:
`make vps-plan`, `vps-apply`, `vps-lockdown`, `ssh`, `push-env`, `deploy`,
`logs-remote`. The sections below describe the compose stack itself, and
the local `make up` workflow that still works on the Mac. The "Sleep-disable
(Mac host)" section applies only to the Phase 2 Mac run.

## Prerequisites

- Docker Desktop (or equivalent) running locally.
- A `.env` file at the repo root, copied from `.env.example`, with at
  least `FREQTRADE__API_SERVER__USERNAME`, `FREQTRADE__API_SERVER__PASSWORD`,
  and `FREQTRADE__API_SERVER__JWT_SECRET_KEY` filled in (any local value —
  these only gate the loopback-bound REST API, see below). No exchange key
  is required for dry-run: `services/freqtrade/user_data/config.dry_run.json`
  ships with `exchange.key` / `exchange.secret` left blank, and Kraken market
  data used for simulated fills is public.

## Sleep-disable (Mac host)

Risk register O1 requires the host not sleep while the stack is expected
to be running. The chosen mechanism, closing the Phase 2 TBD in
[`../docs/07-roadmap.md`](../docs/07-roadmap.md):

- **[Amphetamine](https://apps.apple.com/app/amphetamine/id937984704)**,
  configured to keep the Mac awake indefinitely, including with the lid
  closed (clamshell mode), running in a dedicated always-on macOS login
  session.
- Explicitly **not** `pmset` (system-wide power-management flags, easy to
  leave misconfigured after an OS update) and **not** `caffeinate` (a
  per-process/per-terminal-session assertion — it stops protecting the
  host the moment the shell that launched it exits or the session logs
  out, which is exactly the silent-failure mode risk register O1 is
  about). Amphetamine's assertion is tied to a persistent login session,
  not a shell process, so it survives terminal restarts and SSH
  disconnects.
- This does not replace heartbeat monitoring (NFR4, Phase 3) — it
  addresses the sleep half of risk O1, not the crash/network-partition
  half.

## Start

From the repo root:

```
make up
```

This pulls `freqtradeorg/freqtrade:2026.8` (pinned — never `stable` or
`latest`, per [`../docs/04-architecture/security.md`](../docs/04-architecture/security.md))
and starts one container, `ai-trading-agent-freqtrade`, running
`freqtrade trade` against `config.dry_run.json` with the `Baseline4h`
strategy (real strategy logic landed in work package 2C — see
[`../docs/research/03-baseline-backtest.md`](../docs/research/03-baseline-backtest.md)).

## Verify dry-run is active

```
make logs
```

Look for a startup line reading `Dry run is enabled`. Freqtrade prints
this once at boot, before it starts polling the exchange for candles — if
you don't see it, **do not assume the bot is safe**; stop (`make down`)
and check the config before retrying.

You can also confirm via the REST API (bound to `127.0.0.1:8080` only —
see Network below):

```
curl -u "$FREQTRADE__API_SERVER__USERNAME:$FREQTRADE__API_SERVER__PASSWORD" http://127.0.0.1:8080/api/v1/show_config | grep '"dry_run"'
```

Expect `"dry_run": true`.

## Logs

- `make logs` tails the container's stdout (`docker compose logs -f`).
- The strategy/bot logfile also persists to
  `services/freqtrade/user_data/logs/freqtrade.log` on the host (bind
  mount), gitignored per `.gitignore`.
- The dry-run trade ledger (simulated fills, not the Conductor ledger)
  lives in `services/freqtrade/user_data/tradesv3.dryrun.sqlite`, also
  gitignored.

## Other Makefile targets

- `make download-data` — pulls OHLCV for the whitelisted pairs from
  Kraken's public API into `services/freqtrade/user_data/data/`
  (gitignored; re-run anytime). Runs `scripts/fetch_ohlcv.py --venue kraken`, not
  Freqtrade's own `download-data` command — Freqtrade refuses to run in
  klines mode for Kraken at all (its public OHLC endpoint doesn't serve
  historic klines); see the "Data" section of
  [`../docs/research/03-baseline-backtest.md`](../docs/research/03-baseline-backtest.md)
  for why, and its real (short) coverage limits on the 4h timeframe.
- `make backtest` — runs Freqtrade's backtesting engine against
  `Baseline4h` using downloaded data, with the fee/slippage assumption and
  protections enabled that produced
  [`../docs/research/03-baseline-backtest.md`](../docs/research/03-baseline-backtest.md)
  (work package 2C).
- `make shell` — drops into a throwaway container with a bash shell and
  the same image/mounts, for debugging (`freqtrade` CLI subcommands,
  inspecting `user_data/`).

## Stop

```
make down
```

Stops and removes the container. The bind-mounted `user_data/` (config,
strategies, logs, sqlite DB) persists on the host across `down`/`up`.

## Network

- Only one port is published: `127.0.0.1:8080` → Freqtrade's REST API.
  It is not reachable from outside the host. See
  [`../docs/04-architecture/security.md`](../docs/04-architecture/security.md)
  ("No inbound public ports").
- The API still requires the username/password/JWT secret from `.env` —
  loopback-only is defence in depth, not a reason to leave it open.
- Freqtrade's own Telegram integration was enabled in work package 2D and is
  **disabled** as of 3A-4; Conductor owns the bot — see "Telegram (Conductor's
  bot)" below.

## Telegram (Conductor's bot)

Telegram belongs to **Conductor** (work package 3A-4, ADR-0015). Freqtrade's own
Telegram integration is **disabled** (`telegram.enabled: false` in
`config.dry_run.json`): its ~35 commands (`/forceexit`, `/stop`,
`/reload_config`, ...) had no per-command permission system, so they are simply
gone. Trade open/close notifications now come from Conductor.

- **Long polling only**: Conductor makes outbound HTTPS calls to Telegram; there
  is no webhook and no inbound port.
- **Allowlist**: only chat IDs in `TELEGRAM_ALLOWED_CHAT_IDS` are answered.
  Anyone else gets no reply at all and the attempt is logged by chat ID.
- **Token**: `TELEGRAM_BOT_TOKEN` is passed to the conductor container only
  (the compose file blanks all Telegram variables for the freqtrade container).
- **Commands**: `/status /capital /halts /trades /help` (read) and `/kill
  /flatten /resume <id>` (write, each needs `yes <code>` within 60 s). Nothing
  can open a trade. See `docs/04-architecture/conductor.md`.

**Setup (one-time):**
1. Reuse the bot you already have, or create one with
   [@BotFather](https://t.me/BotFather) (`/newbot`).
2. In `.env` set `TELEGRAM_BOT_TOKEN` to the bot token and
   `TELEGRAM_ALLOWED_CHAT_IDS` to your chat ID (the values that used to be
   `FREQTRADE__TELEGRAM__TOKEN` / `FREQTRADE__TELEGRAM__CHAT_ID`). Then delete
   all three `FREQTRADE__TELEGRAM__*` lines from `.env`, **including
   `FREQTRADE__TELEGRAM__ENABLED=true` if it is there**: Freqtrade lets such
   variables override its config file, so it would re-enable the old bot. (The
   compose file now pins it to `false` regardless, as a safety net.)
3. Restart: `docker compose --env-file .env -f infra/docker-compose.yml up -d`.
   Freqtrade must be recreated too so its Telegram bot stops polling: a bot token
   can be polled by only one process, and two will fight (`409 Conflict`).
4. Within a minute you should get "Conductor started ... telegram=on". Send
   `/status` to confirm it answers.

If the token is wrong or Telegram is unreachable, Conductor keeps running and
keeps enforcing its risk limits; only alerts and commands are unavailable
(check `docker logs ai-trading-agent-conductor`).

## Secret scanning (gitleaks)

A [gitleaks](https://github.com/gitleaks/gitleaks) pre-commit hook is
configured in [`../.pre-commit-config.yaml`](../.pre-commit-config.yaml)
to catch a committed secret before it reaches history (NFR3). One-time
setup:

```
pip install pre-commit   # or: brew install pre-commit
pre-commit install
```

After that, gitleaks runs automatically on every `git commit`, scanning
staged changes. To run it manually against the whole repo (e.g. before a
first public push):

```
pre-commit run gitleaks --all-files
```

If it flags a false positive (e.g. a placeholder that merely looks like a
key), fix the placeholder to be unambiguous rather than suppressing the
hook — see `../CLAUDE.md` §0.3.

## Known gaps (Phase 2 scope)

- The `StoplossGuard`/`MaxDrawdown`/`CooldownPeriod` protections, set on
  the `Baseline4h` strategy's `protections` class attribute (Freqtrade
  2026.8 deprecated the config-level `protections` key — see
  [`../docs/04-architecture/execution-freqtrade.md`](../docs/04-architecture/execution-freqtrade.md)),
  are Freqtrade's own **time-bound** locks — the first of R4's two
  required independent layers (`docs/02-requirements.md` AC4.4). They do
  not by themselves satisfy AC4.2/AC4.6 (a durable halt requiring explicit
  human re-enable); that is the Conductor's own check, Phase 3+. Do not
  treat this alone as a complete R4 implementation.
- Backtest history on the 4h timeframe is short (~4 months) because
  Kraken's public API will not serve more — see
  [`../docs/research/03-baseline-backtest.md`](../docs/research/03-baseline-backtest.md).
  `Baseline4h` does not clear Gate 1 (`../docs/08-paper-exit-criteria.md`)
  as a result; not expected to at this stage.

## Troubleshooting

- **`make up` / `docker pull` hangs indefinitely** (image pull never
  progresses, no error, no timeout): on macOS this has been caused by
  Docker Desktop's "Use kernel networking for UDP" setting conflicting
  with Tailscale. Fix: Docker Desktop → Settings → Resources → Network →
  uncheck **"Use kernel networking for UDP"** → Apply & restart. Retry
  `make up` after Docker Desktop finishes restarting.
