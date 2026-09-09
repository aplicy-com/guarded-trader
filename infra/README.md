# Infra

Work package 2A (`docs/phase-2-plan.md`) — Freqtrade running in Docker,
dry-run only. Conductor and the ledger DB are added in Phase 3; this
compose file runs Freqtrade alone. See
[`../docs/04-architecture/overview.md`](../docs/04-architecture/overview.md)
for the target container diagram and
[`../docs/04-architecture/execution-freqtrade.md`](../docs/04-architecture/execution-freqtrade.md)
for why Freqtrade is configured the way it is.

## Prerequisites

- Docker Desktop (or equivalent) running locally.
- A `.env` file at the repo root, copied from `.env.example`, with at
  least `FREQTRADE__API_SERVER__USERNAME`, `FREQTRADE__API_SERVER__PASSWORD`,
  and `FREQTRADE__API_SERVER__JWT_SECRET_KEY` filled in (any local value —
  these only gate the loopback-bound REST API, see below). No exchange key
  is required for dry-run: `services/freqtrade/user_data/config.dry_run.json`
  ships with `exchange.key` / `exchange.secret` left blank, and Kraken market
  data used for simulated fills is public.

## Start

From the repo root:

```
make up
```

This pulls `freqtradeorg/freqtrade:2026.8` (pinned — never `stable` or
`latest`, per [`../docs/04-architecture/security.md`](../docs/04-architecture/security.md))
and starts one container, `ai-trading-agent-freqtrade`, running
`freqtrade trade` against `config.dry_run.json` with the `Baseline4h`
placeholder strategy (real strategy logic lands in work package 2C).

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

- `make download-data` — pulls historical OHLCV from Kraken's public API
  into `services/freqtrade/user_data/data/` (gitignored; re-run anytime).
- `make backtest` — runs Freqtrade's backtesting engine against
  `Baseline4h` using downloaded data. Real backtest documentation is work
  package 2C (`docs/research/03-baseline-backtest.md`).
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
- Freqtrade's own Telegram integration is present in
  `config.dry_run.json` but `enabled: false` — work package 2D turns it on
  (status-only) once dry-run is stable.

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
- `download-data` / `backtest` defaults are provisional; work packages 2B
  (market facts) and 2C (baseline strategy + backtest) refine the pair
  universe and cost assumptions used here.

## Troubleshooting

- **`make up` / `docker pull` hangs indefinitely** (image pull never
  progresses, no error, no timeout): on macOS this has been caused by
  Docker Desktop's "Use kernel networking for UDP" setting conflicting
  with Tailscale. Fix: Docker Desktop → Settings → Resources → Network →
  uncheck **"Use kernel networking for UDP"** → Apply & restart. Retry
  `make up` after Docker Desktop finishes restarting.
