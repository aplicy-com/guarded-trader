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
| Conductor ledger | `backups/<mode>/conductor/conductor-<UTC time>-<random>.sqlite.gz` |
| Freqtrade DB (dry-run or live trade DB) | `backups/<mode>/freqtrade/freqtrade-<UTC time>-<random>.sqlite.gz` |

`<mode>` is `dry_run` or `live` (ADR-0019): the stack that wrote the backup. **Every
restore command below takes the mode, and there is no default**: the live ledger
(the $20 pilot) and the dry-run ledger must never be mistaken for each other. Which
mode am I? On the VPS, `scripts/trading-mode.sh status` prints `mode: dry-run` or
`mode: live` (`live-pending` counts as `live`). Use `--mode live` for `live`/`live-pending`
and `--mode dry_run` for `dry-run`. Backups made before this split (up to the first
nightly run after it was deployed) are dry-run backups under the old
`backups/<source>/...` keys; read them with `--mode legacy`.

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

**A4. Run the test** (use the mode you are testing, `live` or `dry_run`):
```
scripts/restore-test.sh --mode dry_run all
```
Expected, for each of `conductor` and `freqtrade`, a block like:
```
== conductor  (mode: dry_run)
   latest : backups/dry_run/conductor/conductor-20261005T031512Z-a1b2c3.sqlite.gz
   stored : 2026-10-05T03:15:14+00:00  (6 h ago)
   downloaded 48213 bytes
   integrity_check: ok
   row counts:
    audit_log                42
    ...
    trades                   17
   principal: 100 USD        (a live ledger shows 20 USD)
   halts still active in this copy: (none)
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
(`scripts/restore-test.sh --mode <mode> all --keep ~/restore-check`, then
`sqlite3 -readonly ~/restore-check/conductor.sqlite`). They contain your trade
history: delete the directory when you are done (`rm -rf ~/restore-check`).

**A8. Clean up:**
```
unset RESTORE_B2_KEY_ID RESTORE_B2_APP_KEY
```
Then, in the B2 console, **delete the `restore-test` key**.

**A9. Record it.** Note the date and result for the 3A-6 drill record
([`docs/drills/`](../drills/README.md), drill 5).

## Part B — Real restore (onto the VPS)

Use this only when you actually need the old data back. This Part B replaces the data of a
**running** system. To restore onto a freshly rebuilt server that has never
been started, use [`rebuild-vps.md`](rebuild-vps.md) step 7 instead (its order
avoids starting an empty ledger first). A restore **rewinds
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
scripts/restore-test.sh --mode <mode> conductor --keep ~/restore-live
```
Expected: `RESTORE TEST PASSED` and `kept at: .../restore-live/conductor.sqlite`.
(Use `freqtrade` instead of `conductor` to restore Freqtrade's database.)

**B2. Copy it to the VPS** (over Tailscale):
```
scp -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes ~/restore-live/conductor.sqlite deploy@ai-trader-vps:/tmp/conductor.sqlite
```
Expected: the file name and a size, no error.

**B3. On the VPS, stop Conductor** (every `docker compose ...` in this part is
`scripts/compose.sh ...` while the server is live: it adds the live override) (Freqtrade can keep running; it manages its
own open positions):
```
make ssh
cd /opt/ai-trading-agent
docker compose --env-file .env -f infra/docker-compose.yml stop conductor
```
Expected: `Container ai-trading-agent-conductor  Stopped`.

**B4. Move the current ledger aside, then put the restored one in place.** The
ledger lives in the Docker volume `infra_conductor-data` (dry-run) or
`infra_conductor-data-live` (live): **use the volume that matches the backup's
mode, and replace `infra_conductor-data` below with `infra_conductor-data-live`
for live**. Restoring a `dry_run` backup into the live volume (or the reverse)
is refused by Conductor (principal 100 vs 20) but do not rely on that. This uses
Conductor's own image so the file gets the right owner:
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
Expected: the halts you expect (or `no active halts`), and `principal: 100` (`20` for the live ledger)
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
back in time. **For the live stack** the file is `tradesv3.live.sqlite` (restore the
`--mode live` backup of `freqtrade`), and Freqtrade must come back `paused` with
`dry_run=False`; its open positions and exchange stop orders are real, so check
Kraken's Open orders before and after (a restored database that disagrees with the
exchange is a finding, not something to start trading on: `/kill` first).

## Troubleshooting

- **`FAILED: could not list ... Is this a READ key?`** You used the write-only
  key, or the key is limited to a different bucket, or `BACKUP_B2_BUCKET` is
  wrong. Re-check A2/A3.
- **`FAILED: no backups found under backups/<mode>/<source>/`** Backups have never
  succeeded for that source *in that mode*. Right after the mode split was
  deployed, dry-run backups are still under the old keys: use `--mode legacy`
  (the script says so). Otherwise check you passed the right mode: a server that
  has never been live has no `live` backups. Check the dashboard's *Overview* (Backups line) and
  the audit log (*Halts & audit*) for `backup_failed` rows, then
  `make ssh` and `docker logs ai-trading-agent-conductor 2>&1 | grep backup`.
- **No recent backup** (`WARNING: ... older than 36 h`, or the dashboard shows
  *stale*). On the VPS, run it by hand and read the result:
  ```
  docker exec ai-trading-agent-conductor python -m conductor.cli backup-now
  ```
  Expected: `conductor: ok backups/<mode>/conductor/...` and `freqtrade: ok backups/<mode>/freqtrade/...`.
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
