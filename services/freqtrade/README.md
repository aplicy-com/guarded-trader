# Freqtrade

**Status: placeholder — implementation starts Phase 2.**

This directory will hold the Freqtrade service configuration and
`user_data/` (strategies, config, backtest results) that runs as a
separate Docker service, driven by Conductor. See
[`../../docs/05-adr/0001-freqtrade.md`](../../docs/05-adr/0001-freqtrade.md)
for why Freqtrade, and
[`../../docs/04-architecture/execution-freqtrade.md`](../../docs/04-architecture/execution-freqtrade.md)
for how it's configured.

Freqtrade is GPL-3 licensed and runs as an external service (its own
Docker container, communicated with only via its REST API) — nothing in
this repository vendors or modifies Freqtrade's own source, so this
repo's Apache-2.0 licence is unaffected
([`../../docs/05-adr/0006-apache-2-licence.md`](../../docs/05-adr/0006-apache-2-licence.md)).

Nothing in this directory connects to an exchange yet. Phase 2 will add,
after a written and approved plan (`CLAUDE.md` §1):

- `user_data/strategies/` — strategy Python classes, git-pinned per
  promotion stage.
- `user_data/config-dry-run.json` / `config-live.json` — dry-run vs. live
  configuration (see execution architecture doc for the split).
- Protections configuration (`StoplossGuard`, `MaxDrawdown`,
  `CooldownPeriod`, `LowProfitPairs`).
- Pair whitelist (majors only, per
  [`../../docs/05-adr/0005-low-frequency-only.md`](../../docs/05-adr/0005-low-frequency-only.md)).

See the [roadmap](../../docs/07-roadmap.md) Phase 2 entry/exit gates
before starting implementation here.
