# Runbook — Restore test and restore from backup

**When to use:**
- **Part A (restore test):** after the first deploy of backups, in the 3A-6
  drill, and whenever you want proof the backups are usable. It changes
  nothing on the VPS or in B2.
- **Part B (real restore):** the ledger or Freqtrade's database on the VPS
  is lost, corrupt or wrong, and you want the last good copy back.

**Decision record:** [`ADR-0016`](../05-adr/0016-backups-write-only-key-no-client-side-encryption.md).
**Code:** [`scripts/restore-test.sh`](../../scripts/restore-test.sh) (runs on
your Mac), the nightly job in Conductor (`application/backup.py`).

**What the backups are:** every night at 03:15 UTC, two files are uploaded to
your Backblaze B2 bucket as gzipped SQLite copies:

| Source | B2 key pattern |
|---|---|
| Conductor ledger | `backups/conductor/conductor-<UTC time>-<random>.sqlite.gz` |
| Freqtrade dry-run DB | `backups/freqtrade/freqtrade-<UTC time>-<random>.sqlite.gz` |

B2's lifecycle rule deletes files after 30 days. The VPS holds a
**write-only** key: it can upload but cannot list, read or delete, so this
runbook needs a second, **read** key that you create just for it.

**Rules while you do this:**
- The read key goes only into your shell environment (step A3), never into a
  file, a commit or a chat. Delete it in B2 when you are done (step A8).
- If any "Expected" line does not match, **stop** and go to Troubleshooting.

## Part A — Restore test (from your Mac)

**A1. Check the tools exist:**
```
aws --version && sqlite3 --version && gzip --version | head -1
```
Expected: three version lines. If `aws` is missing: `brew install awscli`.

**A2. Create a read key in Backblaze.** B2 web console → App Keys → *Add a New
Application Key*. Name it `restore-test`, allow access to **only your backup
bucket**, type **Read Only**. Copy the `keyID` and `applicationKey` (shown
once).

**A3. Put the key in your shell (nothing is written to disk).** In zsh:
```
read -rs "RESTORE_B2_KEY_ID?Read key ID: ";  export RESTORE_B2_KEY_ID;  echo
read -rs "RESTORE_B2_APP_KEY?Read app key: "; export RESTORE_B2_APP_KEY; echo
export BACKUP_B2_BUCKET=<your bucket name>
export BACKUP_B2_ENDPOINT=<your endpoint, e.g. https://s3.us-west-004.backblazeb2.com>
```
(The bucket and endpoint are the same values as in your `.env`; they are not
secret. Do **not** `source .env` here: the key in it is the write-only one.)

**A4. Run the test:**
```
scripts/restore-test.sh
```
Expected, for each of `conductor` and `freqtrade`, a block like:
```
== conductor
   latest : backups/conductor/conductor-20261005T031512Z-a1b2c3.sqlite.gz
   stored : 2026-10-05T03:15:14+00:00  (6 h ago)
   downloaded 48213 bytes
   integrity_check: ok
   row counts:
    audit_log                42
    ...
    trades                   17
   principal: 100 USD
   latest audit entry: 2026-10-05T03:15:14.000000+00:00  backup_completed
```
and, last, `RESTORE TEST PASSED` (exit status 0).

**A5. Judge the numbers.** The row counts must be plausible for the age of the
backup: `trades` is not zero if the system has traded, `principal` is 100 USD,
and the latest audit entry is recent. "Passed" with an empty `trades` table on
a system that has traded means the backup is of the wrong or a fresh database:
treat that as a failure.

**A6. If it says `WARNING: the latest backup is older than 36 h`** the nightly
job is not running. Go to Troubleshooting ("No recent backup").

**A7. Optional: keep the restored copies** to inspect them
(`scripts/restore-test.sh all --keep ~/restore-check`, then
`sqlite3 -readonly ~/restore-check/conductor.sqlite`). They contain your trade
history: delete the directory when you are done (`rm -rf ~/restore-check`).

**A8. Clean up:**
```
unset RESTORE_B2_KEY_ID RESTORE_B2_APP_KEY
```
Then, in the B2 console, **delete the `restore-test` key**.

**A9. Record it.** Note the date and result for the 3A-6 drill record
(`docs/drills/`).

## Part B — Real restore (onto the VPS)

Use this only when you actually need the old data back. A restore **rewinds
that database to the time of the backup**; anything after it is gone from that
file. Read the three consequences first:

- **A halt can be lost.** If a halt (including a kill switch) was raised after
  the backup was taken, the restored ledger does not know about it. After the
  restore, check `/halts` on the dashboard or `/status` on Telegram, and
  re-apply `/kill` if you had one active.
- **Trades since the backup come back by themselves.** Conductor re-imports
  closed and open trades from Freqtrade's API on its next ingest, so restoring
  only the *ledger* loses nothing as long as Freqtrade's own database is intact.
  Realised-profit fences and manual-transfer records made after the backup do
  **not** come back: re-enter any `record-transfer` you made since.
- **Profit already fenced stays fenced only if it is in the backup.** Check
  `capital` (step B6) against what you expect before trading resumes.

**B1. Get a restored copy on your Mac** (Part A, steps A1-A4, with `--keep`):
```
scripts/restore-test.sh conductor --keep ~/restore-live
```
Expected: `RESTORE TEST PASSED` and `kept at: .../restore-live/conductor.sqlite`.
(Use `freqtrade` instead of `conductor` to restore Freqtrade's database.)

**B2. Copy it to the VPS** (over Tailscale):
```
scp -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes ~/restore-live/conductor.sqlite deploy@ai-trader-vps:/tmp/conductor.sqlite
```
Expected: the file name and a size, no error.

**B3. On the VPS, stop Conductor** (Freqtrade can keep running; it manages its
own open positions):
```
make ssh
cd /opt/ai-trading-agent
docker compose --env-file .env -f infra/docker-compose.yml stop conductor
```
Expected: `Container ai-trading-agent-conductor  Stopped`.

**B4. Move the current ledger aside, then put the restored one in place.** The
ledger lives in the Docker volume `infra_conductor-data`. This uses Conductor's
own image so the file gets the right owner:
```
docker run --rm --entrypoint sh -v infra_conductor-data:/data ai-trading-agent-conductor:0.1.0 \
  -c 'mv /data/conductor.db /data/conductor.db.before-restore; rm -f /data/conductor.db-wal /data/conductor.db-shm'
docker run --rm --entrypoint sh -v infra_conductor-data:/data -v /tmp:/in:ro ai-trading-agent-conductor:0.1.0 \
  -c 'cp /in/conductor.sqlite /data/conductor.db && ls -l /data'
```
Expected: `ls` shows `conductor.db` and `conductor.db.before-restore`, both owned
by `conductor`.

**B5. Start Conductor:**
```
docker compose --env-file .env -f infra/docker-compose.yml up -d conductor
```
Expected: `Container ai-trading-agent-conductor  Started`. If it exits with
`STARTUP REFUSED` or `CONFIG ERROR`, read the message: it says why (for
example a principal that does not match `PRINCIPAL_USD`). Do not edit the
database by hand; go to Troubleshooting.

**B6. Check it is healthy:**
```
docker exec ai-trading-agent-conductor python -m conductor.cli halts
docker exec ai-trading-agent-conductor python -m conductor.cli capital
```
Expected: the halts you expect (or `no active halts`), and `principal: 100`
with fenced / working profit as you expect.

**B7. Re-apply anything the backup could not know about** (a kill switch, a
`record-transfer`). Then confirm on Telegram with `/status`.

**B8. Clean up** on the VPS: `rm /tmp/conductor.sqlite`. The
`conductor.db.before-restore` file stays in the volume until you are sure; remove
it later with the same `docker run ... rm` pattern. On your Mac:
`rm -rf ~/restore-live`.

**B9. Restoring Freqtrade's database** is the same idea, but the file is a plain
bind mount: stop Freqtrade (`docker compose ... stop freqtrade`), move
`services/freqtrade/user_data/tradesv3.dryrun.sqlite*` aside, copy the restored
file in as `tradesv3.dryrun.sqlite` (mode 0644), start Freqtrade, and confirm
with `/status` that it is in dry-run. Note that this moves the Gate 2 evidence
back in time.

## Troubleshooting

- **`FAILED: could not list ... Is this a READ key?`** You used the write-only
  key, or the key is limited to a different bucket, or `BACKUP_B2_BUCKET` is
  wrong. Re-check A2/A3.
- **`FAILED: no backups found under backups/<source>/`** Backups have never
  succeeded for that source. Check the dashboard's *Overview* (Backups line) and
  the audit log (*Halts & audit*) for `backup_failed` rows, then
  `make ssh` and `docker logs ai-trading-agent-conductor 2>&1 | grep backup`.
- **No recent backup** (`WARNING: ... older than 36 h`, or the dashboard shows
  *stale*). On the VPS, run it by hand and read the result:
  ```
  docker exec ai-trading-agent-conductor python -m conductor.cli backup-now
  ```
  Expected: `conductor: ok backups/conductor/...` and `freqtrade: ok backups/freqtrade/...`.
  A `FAILED` line says why (for example `unable to open database file` for
  `freqtrade`: the read-only mount of Freqtrade's directory is missing, check
  `docker compose ... config | grep freqtrade-user-data`).
- **`FAILED: integrity_check`** The stored copy is corrupt, which should be
  impossible (the job checks before uploading). Try the previous night's backup
  by downloading it by hand, and treat this as an incident: record the key and
  time.
- **`unable to open database file` for `freqtrade` only while Freqtrade is
  stopped.** Expected to be handled automatically; if you see it with Freqtrade
  stopped, the `user_data` mount is wrong.
- **Conductor will not start after a restore (`STARTUP REFUSED`).** Move the
  restored file aside (reverse step B4 with `.before-restore`) and start again,
  then stop and ask for help with the exact message.
