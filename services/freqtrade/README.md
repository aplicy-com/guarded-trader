# Freqtrade

**Status: work package 2A landed (infra skeleton, dry-run only).** No
exchange key exists yet; dry-run uses public Kraken market data only.

This directory holds the Freqtrade service configuration and `user_data/`
(strategies, config, logs, backtest results) that runs as a separate
Docker service — for now started directly via
[`../../infra/docker-compose.yml`](../../infra/docker-compose.yml) and
[`../../Makefile`](../../Makefile); driven by Conductor from Phase 3
onward. See
[`../../docs/05-adr/0001-freqtrade.md`](../../docs/05-adr/0001-freqtrade.md)
for why Freqtrade, and
[`../../docs/04-architecture/execution-freqtrade.md`](../../docs/04-architecture/execution-freqtrade.md)
for how it's configured. Start/stop/verify instructions live in
[`../../infra/README.md`](../../infra/README.md), not here.

Freqtrade is GPL-3 licensed and runs as an external service (its own
Docker container, communicated with only via its REST API) — nothing in
this repository vendors or modifies Freqtrade's own source, so this
repo's Apache-2.0 licence is unaffected
([`../../docs/05-adr/0006-apache-2-licence.md`](../../docs/05-adr/0006-apache-2-licence.md)).

Current contents:

- `user_data/config.dry_run.json` — dry-run config: `dry_run: true`,
  $100 simulated wallet, USD stake, `max_open_trades: 3`, 4h timeframe,
  Kraken exchange block with blank key/secret, pair whitelist
  (BTC/ETH/SOL vs. USD — expands in 2B), pair blacklist for assets already
  held outside this system (R5), and the `CooldownPeriod` /
  `StoplossGuard` / `MaxDrawdown` protections (R4 layer 1 of 2 — see
  `infra/README.md` "Known gaps").
- `user_data/strategies/Baseline4h.py` — placeholder strategy (compiles,
  emits no signals). Real trend-following logic is work package 2C.

Not yet added: `config-live.json` (Phase 2E+, after residency/key
creation), real strategy logic (2C), Telegram status alerts (2D).

See the [roadmap](../../docs/07-roadmap.md) Phase 2 entry/exit gates for
what's still outstanding.
