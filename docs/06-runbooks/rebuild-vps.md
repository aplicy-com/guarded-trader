# Runbook — Rebuild the VPS (destroy and recreate from zero)

**When to use:**
- the VPS is suspected compromised (treat any unexplained login, process
  or open port as compromise);
- cloud-init failed or Tailscale never joined during first provisioning;
- the server is broken beyond a quick fix;
- the rebuild drill (work package 3A-6, drill 6: see
  [`docs/drills/README.md`](../drills/README.md); record the result there).

**Related:** first-time setup is [`provision-vps.md`](provision-vps.md);
this runbook reuses its verification steps rather than repeating them.
Restoring data is [`restore-backup.md`](restore-backup.md) (this runbook
puts the data back **before** the first start, which is different from that
runbook's "replace a running system" flow).

**What survives a rebuild:** the static IPv4 (it is a separate Terraform
resource), the Hetzner firewall, your SSH key resource, everything in git,
everything in LastPass, and the nightly backups in Backblaze B2.
**What does not:** everything on the server's disk (the ledger, Freqtrade's
dry-run database, logs, `/opt/ai-trading-agent/.env`) **and the Tailscale
device**. The rebuilt server is a brand-new tailnet device: new `100.x`
address, and it keeps the name `ai-trader-vps` (and so the same
`https://ai-trader-vps.<tailnet>.ts.net/` dashboard URL) only if the old
device is deleted from the tailnet first (step 3). Any access-control rule
that names the old `100.x` address must be updated (step 6).

**Rules:**
- If you suspect **compromise**, do step 1 and then **skip step 2**. Do
  not copy files off a box you do not trust, and never run anything from
  the box. Restore from B2 instead.
- Treat every secret that was on the box as leaked after a compromise:
  rotate them per [`key-rotation.md`](key-rotation.md) after the rebuild
  (Hetzner API token, Tailscale account keys and sessions, Anthropic key,
  Telegram tokens, Freqtrade API password, healthchecks.io ping URL, the
  B2 keys, and the Kraken key if one exists), and replace the SSH key pair
  `ai_trader_vps`.
- **Do not run `terraform destroy`** to rebuild: it deletes the static IP.
  Use `-replace=hcloud_server.vps` (step 5A).
- If a stop is shown, stop. Do not improvise.
- During the rebuild nothing is managing exits or halts. That is only
  acceptable in dry-run. With real money, flat the book first (see
  "Before you start").

## Before you start

1. If any real-money position could be open (Phase 4 onward), engage the
   [kill switch](kill-switch.md) and, if positions are open, run the
   [nuclear protocol](nuclear-protocol.md), and confirm positions are flat
   before destroying anything. In Phase 3 (dry-run only) there is no real
   position; skip this.
2. **Make a fresh, verified off-host backup first** (skip only if the box is
   compromised and you are restoring an older one). On the VPS:
   ```
   make ssh
   cd /opt/ai-trading-agent
   docker exec ai-trading-agent-conductor python -m conductor.cli kill --operator <your name>
   docker exec ai-trading-agent-conductor python -m conductor.cli backup-now
   exit
   ```
   Expected: `halt #<n> engaged` (or `was already active`), then
   `conductor: ok backups/conductor/...` and `freqtrade: ok backups/freqtrade/...`.
   Engaging the kill switch first pauses new entries, so no trade is opened
   between the backup and the shutdown, and the backup records the halt: after
   the restore the system comes back **halted**, never unguarded.
   Then prove the backup is readable and current, from the Mac
   ([`restore-backup.md`](restore-backup.md) Part A, steps A1-A4; you need a
   B2 **read** key):
   ```
   scripts/restore-test.sh all
   ```
   Expected: `RESTORE TEST PASSED`, `stored:` a few minutes ago, and for
   `conductor` the line `halts still active in this copy: #<n> kill_switch`.
   If it does not show the halt you just made, stop: the backup is not the
   current state.
3. You need: `TF_VAR_hcloud_token` (from LastPass) and a **new** Tailscale
   auth key. Create the key exactly as in `provision-vps.md` step 5
   (Reusable off, Ephemeral off, Expiry 1 day).
4. Write down, before touching anything (they are what "restored" is
   compared against):
   ```
   mkdir -p ~/vps-rebuild-backup && chmod 700 ~/vps-rebuild-backup
   terraform -chdir=infra/terraform output -raw ipv4; echo
   tailscale status --json | python3 -c 'import json,sys; d=json.load(sys.stdin)["Peer"]; print([ (p["HostName"], p["DNSName"], p["TailscaleIPs"][0]) for p in d.values() if p["HostName"]=="ai-trader-vps"])'
   cp -p infra/terraform/terraform.tfstate ~/vps-rebuild-backup/terraform.tfstate.before
   ```
   (The state file holds secrets; that folder is outside the repo and mode 700.) You now have: the static IPv4,
   the tailnet name and the old `100.x` address, and a copy of the Terraform
   state. Also open the VPS dashboard and note the principal, trade count
   and halt id, or run `scripts/drill-check.sh` on the VPS.

## Procedure

### 1. Stop the stack

```
make ssh
cd /opt/ai-trading-agent && docker compose --env-file .env -f infra/docker-compose.yml down
exit
```
Expected: `Container ai-trading-agent-conductor  Removed` and
`Container ai-trading-agent-freqtrade  Removed`.
(If you cannot reach the server over Tailscale, skip to step 3.)

### 2. Copy the databases off as an insurance copy (skip if compromised)

B2 holds the real restore source (step 7). This is the second copy, taken
after a clean stop so both files are consistent. On the Mac:
```
mkdir -p ~/vps-rebuild-backup && chmod 700 ~/vps-rebuild-backup
ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
  'cd /opt/ai-trading-agent/services/freqtrade/user_data && tar czf - tradesv3.dryrun.sqlite*' \
  > ~/vps-rebuild-backup/freqtrade-dbs.tgz
ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
  'docker run --rm --entrypoint tar -v infra_conductor-data:/data:ro ai-trading-agent-conductor:0.1.0 -czf - -C /data .' \
  > ~/vps-rebuild-backup/ledger-volume.tgz
tar tzf ~/vps-rebuild-backup/freqtrade-dbs.tgz; tar tzf ~/vps-rebuild-backup/ledger-volume.tgz
```
Expected: the first listing shows `tradesv3.dryrun.sqlite`, the second shows
`./conductor.db`. If either is empty or errors, decide consciously whether to
continue (B2 still has last night's and your fresh backup). This folder is
outside the repo on purpose. Do not move it into the repo.

### 3. Remove the old machine from the tailnet

Tailscale admin console → Machines → `ai-trader-vps` → ⋯ → **Delete**.
Why: if the old entry stays, the new server joins as `ai-trader-vps-1`,
the dashboard URL changes, and every `make ssh` points at the dead one.
Check it is gone:
```
tailscale status | grep ai-trader-vps
```
Expected: no output.

### 4. Set the secrets in this terminal tab

```
read -rs "TF_VAR_hcloud_token?Hetzner token: "; export TF_VAR_hcloud_token; echo
read -rs "TF_VAR_tailscale_authkey?Tailscale auth key: "; export TF_VAR_tailscale_authkey; echo
[ -n "$TF_VAR_hcloud_token" ] && [ -n "$TF_VAR_tailscale_authkey" ] && echo both-set
```
Expected: `both-set`. Also confirm
`infra/terraform/terraform.tfvars` exists and `admin_cidr` is your
**current** IP (`curl -4 https://ifconfig.me`), and that
`infra/terraform/terraform.tfstate` exists (it is the only record of which
resources exist; without it Terraform would try to create a second server and
IP).

### 5. Recreate

**A. Replace the server, keep the IP (normal case):**
```
terraform -chdir=infra/terraform init -input=false
terraform -chdir=infra/terraform plan -replace=hcloud_server.vps -var bootstrap_ssh=true
```
Expected: `Plan: 1 to add, 1 to change, 1 to destroy.` (`hcloud_server.vps`
replaced, firewall gains its SSH rule) and **no** line saying
`hcloud_primary_ip.ipv4` will be destroyed. If the primary IP is shown
being destroyed, stop.
```
terraform -chdir=infra/terraform apply -replace=hcloud_server.vps -var bootstrap_ssh=true
```
Type `yes`. Expected: `Apply complete! Resources: 1 added, 1 changed, 1 destroyed.`
and `ipv4` **equal to the one you wrote down**. Write down the time.

**B. Destroy everything, including the IP (only to abandon the setup or
move region):**
```
terraform -chdir=infra/terraform destroy
```
This **loses the static IP**. After a destroy and re-provision the new IP
will be different, and any Kraken API-key IP whitelist must be updated to
it (see `key-rotation.md`). Type `yes` only if that is acceptable. Then
follow `provision-vps.md` from step 7 instead of continuing here.

### 6. Verify, join the tailnet, harden, lock down

First boot takes 3-6 minutes. Follow [`provision-vps.md`](provision-vps.md),
in this order, running each step's "Expected" check:
- Step 9 (wait for cloud-init; the host key changed, so first run
  `ssh-keygen -R $IP`) and step 10.
- **6b. Update the Tailscale access rules.** The new device has a new `100.x`
  address (`tailscale status | grep ai-trader-vps`). If your access controls
  name the old address (for example a `"hosts": { "ai-trader-vps": "100.x.y.z" }`
  alias, as in [`security.md`](../04-architecture/security.md) "Tailnet
  access"), change it to the new one now, then use *Preview rules* to confirm
  your own devices can reach `ai-trader-vps` on TCP 22 and 443. Until you do,
  the next step fails even though the server is fine.
- Step 11 (Tailscale reachable; the Mac may still hold the old host key:
  `ssh-keygen -R ai-trader-vps` and `ssh-keygen -R <old 100.x address>`).
  Also check the name: `tailscale status | grep ai-trader-vps` must show
  exactly `ai-trader-vps`, **not** `ai-trader-vps-1`. If it is `-1`, the old
  device was not removed (step 3): delete the stale one in the admin console,
  then on the VPS run `sudo tailscale set --hostname=ai-trader-vps`.
- Step 12 (revoke the auth key).
- Steps 12a and 12b (host firewall and tailnet-only sshd; use the **new**
  `100.x` address for `TS=`).
- Steps 13 and 14 (cloud firewall lockdown), 14a, 15, 16 and 17 (checks and
  the external port scan).

**Do not continue until the port scan in step 17 shows nothing open.**

### 7. Restore secrets and data (before the first start)

The stack has not been started on this server. Putting the data in place now
means the first start already has the old ledger, including its halt, so there
is never a moment where a fresh, un-halted system is trading.

```
make push-env
make deploy-files
```
Expected: `pushed .env -> ...` and the rsync file list (nothing is started).
If this rebuild was a compromise response, rotate secrets first (see Rules),
update your local `.env`, and only then run `make push-env`.

Get the latest backups on the Mac (needs the B2 read key in your shell, as in
[`restore-backup.md`](restore-backup.md) A2-A3):
```
scripts/restore-test.sh all --keep ~/vps-rebuild-backup/restored
```
Expected: `RESTORE TEST PASSED` and `kept at:` for both. Check the numbers
against what you wrote down in "Before you start".
(If B2 is unreachable, use the insurance copy from step 2 instead; see
Troubleshooting.)

Copy them to the VPS:
```
scp -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes \
  ~/vps-rebuild-backup/restored/conductor.sqlite ~/vps-rebuild-backup/restored/freqtrade.sqlite \
  deploy@ai-trader-vps:/tmp/
```
Then on the VPS, create the containers without starting them, and put the data in:
```
make ssh
cd /opt/ai-trading-agent
docker compose --env-file .env -f infra/docker-compose.yml up --no-start --build
docker run --rm --entrypoint sh -v infra_conductor-data:/data -v /tmp:/in:ro ai-trading-agent-conductor:0.1.0 \
  -c 'cp /in/conductor.sqlite /data/conductor.db && ls -l /data'
cp /tmp/freqtrade.sqlite services/freqtrade/user_data/tradesv3.dryrun.sqlite
chmod 0644 services/freqtrade/user_data/tradesv3.dryrun.sqlite
rm /tmp/conductor.sqlite /tmp/freqtrade.sqlite
ls -l services/freqtrade/user_data/*.sqlite
```
Expected: the `up --no-start` prints `Container ai-trading-agent-conductor  Created`
and `Volume "infra_conductor-data"  Created`; `ls -l /data` shows `conductor.db`
owned by `conductor`; the second `ls` lists `tradesv3.dryrun.sqlite` owned by
`deploy`. Nothing is running yet.

### 8. Start and verify the app

Still on the VPS:
```
docker compose --env-file .env -f infra/docker-compose.yml up -d
scripts/drill-check.sh --watch 5
```
Expected: both containers `Started`. In the `--watch` lines, `freqtrade=` may
read `running` for up to about a minute (Freqtrade always boots `running`;
Conductor re-applies the pause from the ledger on its first risk cycle), then
settles on `paused` with `halts=1`. Ctrl-C. If Conductor exits with
`STARTUP REFUSED` or `CONFIG ERROR`, read the message (for example a principal
that does not match `PRINCIPAL_USD`); do not edit the database; go to
Troubleshooting.

Then, on the VPS, `scripts/drill-check.sh --expect-state paused --expect-halts 1`
must print `CHECK PASS`, and its `data` section must match what you wrote down
(principal, trades). Run `provision-vps.md` steps 22 (nothing listens
publicly), 24-25 (HTTPS certificates are on; `tailscale serve` is applied. A
rebuilt server loses that setting; cloud-init tries it, but check) and 27-29
(loopback check, dashboard from the phone, external scan), and 31 (`backup-now`
proves the B2 key works on the new box). Open
`https://ai-trader-vps.<your-tailnet>.ts.net/`: the same URL as before, showing
the old principal, trades and the active halt. In Telegram, `/status` shows the
halt and `/resume <id>` clears it when you are ready (see
[`kill-switch.md`](kill-switch.md) "Re-enabling").

### 9. Wrap up

- Wait ~6 minutes: healthchecks.io goes back to **up** (it alerted while the
  heartbeat was silent; that is expected).
- `rm -rf ~/vps-rebuild-backup` once you have confirmed the restored
  databases are in place and the stack is healthy. In the B2 console delete
  the read key you made for this. `unset RESTORE_B2_KEY_ID RESTORE_B2_APP_KEY`.
- If this was a **drill**: record start time, end time, total minutes, and
  anything that surprised you in `docs/drills/` (work package 3A-6).
- If this was an **incident**: note what you saw and when in the audit
  log / a dated note, and check [`03-risk-register.md`](../03-risk-register.md)
  S7.

## Troubleshooting

- **The plan wants to destroy `hcloud_primary_ip.ipv4`.** Stop. Do not apply.
  Check you used `-replace=hcloud_server.vps` and not `destroy`, and that the
  state file is the right one.
- **The new server is `ai-trader-vps-1` on the tailnet.** See step 6.
- **`make ssh` fails right after the node joined, but the node shows online.**
  The access rules still name the old address (step 6b).
- **B2 restore is impossible** (read key lost, B2 outage). Use the insurance copy
  from step 2, before starting the stack:
  ```
  ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
    'docker run --rm -i --entrypoint tar -v infra_conductor-data:/data ai-trading-agent-conductor:0.1.0 -xzf - -C /data' \
    < ~/vps-rebuild-backup/ledger-volume.tgz
  ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
    'cd /opt/ai-trading-agent/services/freqtrade/user_data && tar xzf -' \
    < ~/vps-rebuild-backup/freqtrade-dbs.tgz
  ```
  (Run it after `up --no-start` in step 7, in place of the `cp` commands.)
- **`STARTUP REFUSED` after the restore.** Do not start with an empty ledger
  to "get going": that records a brand-new principal and loses history.
  Read the message; try the insurance copy or the previous night's B2 backup;
  see [`restore-backup.md`](restore-backup.md) Troubleshooting.
- **cloud-init failed / Tailscale did not join.** Public SSH from `admin_cidr`
  is still open (you have not locked down yet), so
  `ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@$IP 'sudo tail -60 /var/log/cloud-init-output.log'`
  works; if even that does not, use the Hetzner console's web terminal. Fix, or
  re-run step 5A with a **new** auth key. Never lock down before the tailnet
  works.
- **`tailscale serve` times out or the HTTPS certificate fails.** Check "HTTPS
  Certificates" is enabled (admin console → DNS). Let's Encrypt limits repeated
  certificates for the same name (a handful per week), so do not rebuild over
  and over in a day; wait and re-run `sudo tailscale serve --bg --https=443
  http://127.0.0.1:8000`.
