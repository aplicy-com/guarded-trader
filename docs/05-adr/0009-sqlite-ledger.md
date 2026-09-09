# ADR-0009: SQLite for the Conductor ledger database

## Status

Accepted — 2026-09-09 (work package 2F, ahead of Conductor's Phase 3
build — recorded now so Phase 3 starts from a settled decision rather
than re-litigating it, per `docs/phase-2-plan.md` §1)

## Context and problem statement

The Conductor (Phase 3) needs a durable ledger: every fill, the running
principal/working-profit split (R2), fenced-profit records (R3), halt
history (R4), and CAD-equivalent tax records (NFR6). `docs/phase-2-plan.md`
§1 flagged the DB engine as a decision to lock before Phase 3 begins.
Postgres was the original assumption in early drafts
(`docs/04-architecture/overview.md`); this ADR settles it.

## Decision drivers

- Scale: single-operator system, $100 principal, low-frequency trading
  (2–3 open positions max, ADR-0005) — write volume is tiny (at most a
  few dozen ledger rows per day even at the busiest).
- Operational simplicity: fewer moving containers/services to keep
  running and monitored on a single Mac host (risk register O1, O2) is
  itself a reliability win, not just convenience.
- Backup/recovery simplicity (risk register O4): the entire database
  should be trivially copyable as part of routine backup, without a
  separate dump/restore procedure.
- No multi-writer requirement: `CLAUDE.md` §1 already establishes a
  single ledger-writer model (Conductor), so a database designed for
  concurrent multi-client writes brings no benefit here.
- Must not compromise NFR6 (durable, exportable, tax-grade records) or
  NFR1 (auditability/replayability).

## Considered options

- **SQLite** (file-based, WAL mode)
- Postgres (own container/service)
- A managed cloud database (e.g. hosted Postgres)

## Decision outcome

Chosen option: **SQLite, in WAL (write-ahead log) mode**, as a single
file on the trading host, written exclusively by Conductor.

### Rationale

- Freqtrade itself already uses SQLite for its own dry-run/live trade
  state (`services/freqtrade/user_data/tradesv3.dryrun.sqlite`,
  `infra/docker-compose.yml`) — this system is already living with
  SQLite's operational characteristics in practice, and they have been
  fine at this scale.
- One fewer container/service to run, monitor, and keep patched on a
  single Mac host — directly reduces the operational surface area risk
  register O1/O2 already flag as a concern for a single-operator system.
- WAL mode gives adequate concurrent-read-while-writing behaviour for the
  single-writer model this system already requires (`CLAUDE.md` §1); the
  system was never going to have multiple services writing to the ledger
  concurrently regardless of DB engine, so Postgres's multi-writer
  strengths are not being used for anything here.
- Backup is "copy the file" (with SQLite's own backup API for a
  live-safe copy while WAL is in use) — simpler than a Postgres
  dump/restore procedure, directly supporting risk register O4's backup
  requirement rather than adding a second thing to get right.
- A managed cloud database was rejected outright: it would put ledger
  data (financial, tax-relevant, NFR6) on a third-party service the
  system doesn't otherwise depend on, and introduces a network dependency
  for something that should keep working if the host's internet is
  degraded but the host itself is fine.

### Consequences

**Good:**
- Minimal operational footprint; consistent with the "Mac-first,
  single-operator" posture of ADR-0004.
- Ledger, backtest results, and Freqtrade's own state all live as local
  files on the same host, all covered by the same FileVault full-disk
  encryption (risk register S6, confirmed On) and the same backup
  approach.

**Bad / accepted trade-offs:**
- Does not scale to multiple concurrent writers or high write throughput
  — explicitly not needed at this system's scale, but a real ceiling if
  the project ever meaningfully grows beyond a single $100-principal,
  single-operator system. If principal or trading frequency ever scale
  materially (out of scope for Phase 1–4, and R1 forbids principal
  top-ups regardless), this ADR should be revisited rather than silently
  outgrown.
- SQLite file corruption from an ungraceful host shutdown is a real,
  if rare, failure mode — mitigated by WAL mode (more crash-resistant
  than SQLite's default rollback journal) and the risk register O4 backup
  requirement, not eliminated entirely.
- Migration tooling for schema changes still needs to be chosen — left
  genuinely open, tracked in `docs/04-architecture/conductor.md`'s own
  TBD list (Phase 3), not resolved by this ADR.

## More information

This decision covers the Conductor ledger only. It does not change
Freqtrade's own separate `tradesv3.dryrun.sqlite` (already SQLite,
already in place since work package 2A) or imply anything about how
research-loop prompt/response logs (NFR1) are stored — that storage
format is a separate, not-yet-made decision.
