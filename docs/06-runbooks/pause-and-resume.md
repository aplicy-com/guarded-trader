# Runbook — Pause the project (stop the VPS) and resume it later

**When to use:** live trading is paused (2026-10-30, see [`../07-roadmap.md`](../07-roadmap.md)
"Current status") and the VPS should stop running until a revisit trigger fires. Also any
other long, deliberate pause.

**Related:** [`start-stop.md`](start-stop.md) (stack only),
[`rebuild-vps.md`](rebuild-vps.md) (recreating the server; this runbook reuses its steps),
[`restore-backup.md`](restore-backup.md) (B2 read key, `restore-test.sh`),
[`kill-switch.md`](kill-switch.md), [`nuclear-protocol.md`](nuclear-protocol.md).

**Rules:**
- **Never run `terraform destroy`**, for any reason during a pause. It deletes the static IP
  and everything else. The only Terraform command in this runbook is the `apply` used on
  resume, and that one comes from `rebuild-vps.md`.
- **B2 deletes backups after 30 days** (ADR-0016), and a stopped server makes no new ones. So
  about a month into the pause, **B2 holds nothing**. The local copy from step 4 is the only
  copy that lasts. Don't skip step 4. Don't delete it until the project has resumed and run
  for a week.
- **A powered-off Hetzner server is still billed in full.** Hetzner charges for a server until
  it is *deleted*. Step 7 is where you choose: power off (cheap to resume, still billed) or
  delete the server (no server bill, resume means a rebuild). The static IPv4 is a separate,
  small monthly charge for as long as you keep it. Check current prices on Hetzner's own price
  list before choosing.
- If any "Expected" line does not match, stop. Do not improvise.

## Before you start: which mode is the server in?

On the VPS (`make ssh`, then `cd /opt/ai-trading-agent`):
```
scripts/trading-mode.sh status
```
Expected: `mode: dry-run`, `mode: live` or `mode: live-pending` (treat `live-pending` as live).
Use the matching column below everywhere this runbook says `<...>`:

| | dry-run | live (and live-pending) |
|---|---|---|
| Conductor CLI `<cli>` | `docker exec ai-trading-agent-conductor python -m conductor.cli` | `scripts/trading-mode.sh cli` |
| docker compose `<compose>` | `docker compose --env-file .env -f infra/docker-compose.yml` | `scripts/compose.sh` |
| `<mode>` for `restore-test.sh` | `dry_run` | `live` |
| ledger volume `<volume>` | `infra_conductor-data` | `infra_conductor-data-live` |
| Freqtrade trade DB `<tradedb>` | `tradesv3.dryrun.sqlite` | `tradesv3.live.sqlite` |

## Part A — Pause

**A1. Halt trading.** On the VPS:
```
<cli> kill --operator <your name>
```
Expected: `halt #<n> engaged` (or `was already active`). Write down `<n>`. From now on nothing
opens a new position.

**A2. Live only: get flat.** If the mode is live, send `/flatten` on Telegram (see
[`nuclear-protocol.md`](nuclear-protocol.md)). Then check on **Kraken's own website**:
Portfolio shows no position in a whitelisted coin you didn't decide to keep, and Orders shows
**no open orders**. Don't continue until both are true: once the server is off, nothing
manages a position. Dry-run: skip this step.

**A3. Take a fresh off-host backup.** On the VPS:
```
<cli> backup-now
exit
```
Expected: `conductor: ok backups/<mode>/conductor/...` and `freqtrade: ok backups/<mode>/freqtrade/...`.

**A4. Keep a dated local copy (the one that lasts).** On the Mac, from the repo, with a B2
**read** key in your shell ([`restore-backup.md`](restore-backup.md) A2-A3):
```
P=~/Backups/ai-trading-agent/vps-pause-$(date -u +%Y-%m-%d)
mkdir -p "$P" && chmod 700 "$P"
scripts/restore-test.sh --mode <mode> all --keep "$P/restored"
```
Expected: `RESTORE TEST PASSED`; for `conductor`, `halts still active in this copy: #<n>
kill_switch` (the halt from A1); `kept at:` twice. If the halt is not shown, stop: the backup
isn't the current state. Re-do A3.

**A5. Take the insurance copy too** (the files exactly as they are on disk, after a clean stop).
Stop the stack first:
```
make ssh
cd /opt/ai-trading-agent && <compose> down
exit
```
Expected: `Container ai-trading-agent-conductor  Removed` and
`Container ai-trading-agent-freqtrade  Removed`. Then on the Mac (same `P` as A4):
```
ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
  'cd /opt/ai-trading-agent/services/freqtrade/user_data && tar czf - <tradedb>*' > "$P/freqtrade-dbs.tgz"
ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
  'docker run --rm --entrypoint tar -v <volume>:/data:ro ai-trading-agent-conductor:0.1.0 -czf - -C /data .' \
  > "$P/ledger-volume.tgz"
cp -p infra/terraform/terraform.tfstate "$P/terraform.tfstate"
tar tzf "$P/freqtrade-dbs.tgz"; tar tzf "$P/ledger-volume.tgz"
```
Expected: the first listing shows `<tradedb>`, the second `./conductor.db`. The Terraform state
holds secrets: it stays in this mode-700 folder, never in the repo.

**A6. Clean up the read key.** `unset RESTORE_B2_KEY_ID RESTORE_B2_APP_KEY`, and delete that
key in the B2 console.

**A7. Choose how far to stop.** Pick one:

- **Option 1 — Power off (default).** Hetzner Cloud Console → Servers → `ai-trader-vps` →
  **Power → Shut down** (graceful). Expected: status `Off` within a minute. The disk, the
  Tailscale device and the static IP all stay. **Still billed in full.** Go to A8.
- **Option 2 — Delete the server, stop the server bill.** Hetzner Cloud Console → Servers →
  `ai-trader-vps` → **Delete**. Don't tick anything that deletes the Primary IP. Expected:
  the server is gone; Primary IPs still lists `ai-trader-vps-ipv4`. The disk is gone: A4/A5
  are now the only copies besides B2's next 30 days. Then Tailscale admin console → Machines →
  `ai-trader-vps` → **Delete** (otherwise the rebuilt server joins as `ai-trader-vps-1`).
  Go to A8.

Then decide **the static IP**. Keep it if you might resume within months: the Kraken key
whitelist and the dashboard setup stay valid. Release it only if you want that charge gone:
**first** do A9 (delete exchange keys), because a released IP can be handed to a stranger and
your key's whitelist would then point at their server. To release it: Primary IPs →
`ai-trader-vps-ipv4` → Delete. Only possible after Option 2: an IP assigned to a server
can't be deleted.

**A8. Silence the watchdog.** healthchecks.io → this system's check → **Pause**. Otherwise it
pages you every day that the heartbeat is missing.

**A9. Exchange keys.** A paused system needs no exchange key.
- **NDAX** (ADR-0022, not used): delete the read-only key on ndax.io, and remove the
  `NDAX_*` lines from the Mac's `.env`.
- **Kraken:** if you released the IP, or the pause is open-ended, delete the API key on
  Kraken's website and note it in LastPass. A new key is made on resume (`go-live-pilot.md`
  Part C). If you kept the IP and expect to resume soon, keeping the key is acceptable: it is
  IP-whitelisted, has no withdraw or funding permission, and its secret is only in `.env` and
  LastPass.

**A10. Record the pause.** In `docs/07-roadmap.md` "Current status", note the date, the option
chosen in A7, whether the IP was kept, which keys were deleted, and the path of `$P`.

## Part B — Resume

First check the revisit trigger that brought you back is written down in the roadmap. Resuming
infrastructure **does not** resume trading: the system comes back halted (halt `<n>` from A1),
and live trading still needs every gate (`go-live-pilot.md`, `trading-mode.sh live`).

### B-1. After Option 1 (powered off)

1. Hetzner Cloud Console → `ai-trader-vps` → **Power → Power on**. Expected: status `Running`.
2. Wait 2-3 minutes, then on the Mac: `tailscale ping ai-trader-vps`. Expected: a `pong`.
   If not, open the Tailscale admin console: if `ai-trader-vps` shows *Expired*, re-authorise
   it there; if it isn't listed, follow [`provision-vps.md`](provision-vps.md) Troubleshooting.
3. Update the OS before anything else: `make ssh`, then `sudo apt-get update && sudo apt-get
   -y upgrade`, then `sudo reboot` if it asks. Expected: no errors.
4. Ship the current `main` without starting it: `make deploy-files`. Then start the stack:
   `make ssh`, `cd /opt/ai-trading-agent`, `<compose> up -d`.
   Expected: both containers `Up`.
5. Check it: `scripts/drill-check.sh`. Expected: halt `#<n> kill_switch` **active**,
   Freqtrade `paused`, the trade count you had before the pause.
6. healthchecks.io → resume the check. Expected: **up** within about 6 minutes.
7. The nightly 03:15 UTC backup runs again. The next morning, confirm with
   `scripts/restore-test.sh --mode <mode> all` (needs a B2 read key).
8. Clear the halt only when you mean to trade again (dry-run or live), per
   [`kill-switch.md`](kill-switch.md) (`/halts`, `/resume <n>`).

### B-2. After Option 2 (server deleted)

Follow [`rebuild-vps.md`](rebuild-vps.md) from **"Before you start" step 3**, with these
changes:
- Skip its "Before you start" steps 1-2 and Procedure steps 1-3: there is no server to stop or
  copy, and you already deleted the tailnet device in A7.
- Procedure step 5: **leave out `-replace=hcloud_server.vps`** (the server no longer exists).
  Run `terraform -chdir=infra/terraform plan -var bootstrap_ssh=true` first. With the IP kept,
  expect `Plan: 1 to add, 1 to change, 0 to destroy` (the server is created, the firewall gains
  its bootstrap SSH rule). Then the same command with `apply`. With the IP
  released, expect `2 to add` (a new IP too). **If anything shows `to destroy` that isn't the
  old server, stop.** The new IP must then be whitelisted on any new Kraken key
  ([`key-rotation.md`](key-rotation.md)).
- Procedure step 7: B2 may be empty by now. Use the copy from A4 instead: wherever step 7 says
  `~/vps-rebuild-backup/restored/`, use `$P/restored/` (the `vps-pause-<date>` folder). If those
  files are damaged, the A5 tarballs are the fallback (rebuild-vps.md Troubleshooting).
- Then B-1 steps 5-8 above.

## Where things are kept during a pause

| What | Where |
|---|---|
| Ledger + Freqtrade DB, verified copies | `~/Backups/ai-trading-agent/vps-pause-<date>/restored/` |
| Insurance tarballs, Terraform state | `~/Backups/ai-trading-agent/vps-pause-<date>/` |
| Research trial registry (the `N` for DSR) | `services/research/state/registry.sqlite`; dated copy in `~/Backups/ai-trading-agent/research-registry/` (see `services/research/README.md`) |
| Secrets (`.env` values, Hetzner token, keys) | LastPass |
| B2 backups | Backblaze bucket, **gone 30 days after the last one** |

`~/Backups/` is on the Mac only. A second copy on another device (encrypted external drive) is
recommended for a long pause. TBD (operator choice).
