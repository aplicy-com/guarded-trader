# ADR-0016: Nightly off-host backups with a write-only key; no client-side encryption

## Status

Accepted — 2026-10-05 (work package 3A-5). Closes the Phase 3 half of risk O4
(ledger loss) and the "off-host DB backups" mitigation noted under O7. Builds on
[`ADR-0009`](0009-sqlite-ledger.md) (SQLite ledger) and
[`ADR-0011`](0011-vps-hosting-on-hetzner.md) (single VPS, disk not encrypted at rest).

## Context and problem statement

Everything the system knows about money lives in two SQLite files on one VPS
disk: Conductor's ledger (principal, fills, fences, halts, audit log, CAD tax
valuations) and Freqtrade's dry-run database (the Gate 2 evidence). A disk
failure, a bad deploy or a rebuild would lose the tax record and the paper-trading
history. The VPS is also the machine most likely to be compromised, so whatever it
can do to the backups matters as much as having them.

## Decision outcome

1. **What and when.** Every night at 03:15 UTC, Conductor backs up its own ledger
   and Freqtrade's dry-run DB. 03:15 is after the 00:05 fence run and clear of the
   05:30 unattended-upgrade reboot. The job is outside the ledger lock, so a slow
   upload can never delay a risk cycle.
2. **Consistent copies, verified before upload.** SQLite's online backup API
   (never a file copy: both databases are WAL and being written), then
   `PRAGMA integrity_check` on the *copy*, then gzip. A copy that fails its check
   is never uploaded and raises an alert. The copy is switched to
   `journal_mode=DELETE`, so a restored file is one self-contained file.
3. **Freqtrade's DB is read through a read-only mount** of its `user_data`
   directory (the DB is WAL, so a lone file would hide its `-wal`/`-shm` and give a
   stale copy), opened `mode=ro`. If Freqtrade has been stopped cleanly the `-wal`
   and `-shm` no longer exist and a read-only mount cannot recreate them; only
   then, and only when no `-wal` file exists, the snapshot retries with
   `immutable=1` (no writer exists, nothing is unmerged; the integrity check on
   the copy is the backstop). Conductor never writes to that mount.
4. **A write-only credential, and code that only ever calls PutObject.** The B2
   application key can upload and nothing else (no list, head, read or delete);
   restricting it to the one bucket is also expected (operator-side, checked in the
   runbook). The object-store port has a single operation,
   `put`, so no code path can depend on reading back. Each upload uses a fresh,
   dated, unique key (`backups/<mode>/<source>/<source>-<UTC timestamp>-<random>.sqlite.gz`, mode `live` or `dry_run`; the `<mode>/` segment was added by ADR-0019, older keys are `backups/<source>/...`),
   so nothing is ever overwritten, and a compromised VPS can add garbage but cannot
   delete or replace good backups. B2's lifecycle rule (delete after 30 days) is
   the only thing that removes files.
5. **No client-side encryption.** Backblaze server-side encryption is on; we add no
   encryption of our own. Reasoning:
   - The only key we could use would have to live on the VPS, next to the data and
     the upload credential. It would not protect against the threat that matters
     most (VPS compromise) and would protect only against Backblaze-side exposure
     and a Backblaze account takeover.
   - A key we must remember is a way to lose the backups. The restore runbook is
     written for a half-asleep reader (`CLAUDE.md` §1); a second secret to fetch
     from the password manager at 2am, and a way for a typo to make every backup unreadable,
     is a real cost for a $100, paper-trading system.
   - The files contain trade history, principal and fence figures and operator
     Telegram chat IDs. They contain **no API keys, tokens or seed phrases**
     (those never enter either database), so a leak is a privacy and tax-record
     exposure, not a loss of funds.
   - Mitigations that do exist: B2 SSE, MFA on the Backblaze account, bucket not
     public, and the write-only key.

   **Revisit** (new ADR) if any of these change: live trading with real balances,
   anything secret or personal is added to either database, backups go to a
   provider whose account security we trust less, or a regulator or accountant
   asks for it.
6. **Failure handling.** Each source is backed up independently (one failing never
   skips the other). Every outcome is a row in the ledger audit log
   (`backup_completed` with key, sizes, SHA-256 of the gzipped file and the store's
   ETag; `backup_failed` with the error). Any failure sends one Telegram alert. The
   dashboard shows the last success per source and flags "stale" after 26 h.
   A backup's own audit row is written after its copy was taken, so it is in the
   *next* backup, not its own.

## Consequences

- **An upload cannot be verified by reading it back.** Write-only means the
  authoritative proof that a backup is restorable is the restore drill
  (`scripts/restore-test.sh`, [`restore-backup.md`](../06-runbooks/restore-backup.md)),
  run with a read key supplied at the time. First run after the first deploy and in
  the 3A-6 drill; the cadence afterwards is TBD (Phase 3).
- A successful PutObject is evidence the bytes were accepted, not that they are
  intact; the SHA-256 in the audit log lets the restore drill's download be checked
  against what was sent.
- A job that never fires produces no failure alert. The heartbeat covers "Conductor
  is down or its scheduler stopped"; the dashboard's stale flag covers the rest.
- Backups are 30 days deep at most. A problem noticed after that is not recoverable
  from B2; it is a TBD (Phase 4) question whether to keep monthly copies.
- Adds `boto3` as a dependency (used only in `infrastructure/observability.py`).
  B2's S3 API does not accept boto3's newer default checksum trailers, so the
  client is configured `when_required`; this was not exercised against real B2 in
  development (only against an S3 emulator), so the first `backup-now` on the VPS
  is the real proof.
