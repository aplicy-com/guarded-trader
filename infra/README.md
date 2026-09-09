# Infra

**Status: placeholder — implementation starts Phase 2.**

This directory will hold the `docker-compose.yml` (and any supporting
infra config — Tailscale setup notes, backup scripts) that runs the
Conductor and Freqtrade services together on the trading host. See
[`../docs/04-architecture/overview.md`](../docs/04-architecture/overview.md)
for the container diagram this compose file implements.

Nothing in this directory connects to an exchange yet. Phase 2 will add,
after a written and approved plan (`CLAUDE.md` §1):

- `docker-compose.yml` — `freqtrade` service (Phase 2), `conductor` and
  ledger DB services (Phase 3), pinned image tags/digests (not `latest`,
  per [`../docs/04-architecture/security.md`](../docs/04-architecture/security.md)).
- Network config consistent with the no-public-inbound-ports posture in
  the security architecture doc (Tailscale for remote access).
- Backup scripts for the ledger DB (mechanism TBD, Phase 3 — see risk
  register O4).

See the [roadmap](../docs/07-roadmap.md) Phase 2 entry/exit gates before
starting implementation here.
