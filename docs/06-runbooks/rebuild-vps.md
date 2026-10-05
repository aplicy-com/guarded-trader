# Runbook — Rebuild the VPS (destroy and recreate from zero)

**When to use:**
- the VPS is suspected compromised (treat any unexplained login, process
  or open port as compromise);
- cloud-init failed or Tailscale never joined during first provisioning;
- the server is broken beyond a quick fix;
- the scheduled rebuild drill (work package 3A-6; record the result in
  `docs/drills/`).

**Related:** first-time setup is [`provision-vps.md`](provision-vps.md);
this runbook reuses its verification steps rather than repeating them.

**What survives a rebuild:** the static IPv4 (it is a separate Terraform
resource), the Hetzner firewall, your SSH key resource, everything in git,
and everything in LastPass.
**What does not:** everything on the server's disk: the Freqtrade dry-run
database, logs, and `/opt/ai-trading-agent/.env`. Until nightly off-host
backups exist (work package 3A-5), history survives only if you copy the
databases off in step 2.

**Rules:**
- If you suspect **compromise**, do step 1 and then **skip step 2**. Do
  not copy files off a box you do not trust, except the SQLite databases
  if you accept that risk knowingly, and never run anything from the box.
- Treat every secret that was on the box as leaked after a compromise:
  rotate them per [`key-rotation.md`](key-rotation.md) after the rebuild
  (Hetzner API token, Tailscale account keys and sessions, Anthropic key,
  Telegram tokens, Freqtrade API password, and the Kraken key if one
  exists), and replace the SSH key pair `ai_trader_vps`.
- If a stop is shown, stop. Do not improvise.

## Before you start

1. If any real-money position could be open (Phase 4 onward), engage the
   [kill switch](kill-switch.md) first and confirm positions are flat
   before destroying anything. In Phase 3 (dry-run only) there is no real
   position; skip this.
2. You need: `TF_VAR_hcloud_token` (from LastPass) and a **new** Tailscale
   auth key. Create the key exactly as in `provision-vps.md` step 5
   (Reusable off, Ephemeral off, Expiry 1 day).

## Procedure

### 1. Stop the stack

```
make ssh
cd /opt/ai-trading-agent && docker compose -f infra/docker-compose.yml down
exit
```
Expected: `Container ai-trading-agent-freqtrade  Removed`.
(If you cannot reach the server over Tailscale, skip to step 3.)

### 2. Copy the databases off (skip if compromised)

On the Mac:
```
mkdir -p ~/vps-rebuild-backup && chmod 700 ~/vps-rebuild-backup
ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
  'cd /opt/ai-trading-agent/services/freqtrade/user_data && tar czf - *.sqlite' \
  > ~/vps-rebuild-backup/freqtrade-dbs.tgz
tar tzf ~/vps-rebuild-backup/freqtrade-dbs.tgz
```
Expected: the listing shows `tradesv3.dryrun.sqlite`. If the tar is empty
or errors, decide consciously whether to continue without history.
This folder is outside the repo on purpose. Do not move it into the repo.

### 3. Remove the old machine from the tailnet

Tailscale admin console → Machines → `ai-trader-vps` → ⋯ → **Delete**.
Why: if the old entry stays, the new server joins as `ai-trader-vps-1`
and every `make ssh` points at the dead one.

### 4. Set the secrets in this terminal tab

```
read -rs "TF_VAR_hcloud_token?Hetzner token: "; export TF_VAR_hcloud_token; echo
read -rs "TF_VAR_tailscale_authkey?Tailscale auth key: "; export TF_VAR_tailscale_authkey; echo
[ -n "$TF_VAR_hcloud_token" ] && [ -n "$TF_VAR_tailscale_authkey" ] && echo both-set
```
Expected: `both-set`. Also confirm
`infra/terraform/terraform.tfvars` exists and `admin_cidr` is your
**current** IP (`curl -4 https://ifconfig.me`).

### 5. Recreate

**A. Replace the server, keep the IP (normal case):**
```
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
and the same `ipv4` as before.

**B. Destroy everything, including the IP (only to abandon the setup or
move region):**
```
terraform -chdir=infra/terraform destroy
```
This **loses the static IP**. After a destroy and re-provision the new IP
will be different, and any Kraken API-key IP whitelist must be updated to
it (see `key-rotation.md`). Type `yes` only if that is acceptable. Then
follow `provision-vps.md` from step 7 instead of continuing here.

### 6. Verify, then lock down

Follow [`provision-vps.md`](provision-vps.md), in this order:
- Step 9 (wait for cloud-init; the host key changed, so first run
  `ssh-keygen -R $IP`) and step 10.
- Step 11 (Tailscale reachable; if the Mac still shows the old host key,
  run `ssh-keygen -R ai-trader-vps`).
- Step 12 (revoke the auth key).
- Steps 13–17 (lockdown and external port scan).

**Do not continue until the port scan in step 17 shows nothing open.**

### 7. Restore secrets and data

```
make push-env
```
Expected: the `pushed .env -> …` line. If this rebuild was a compromise
response, rotate secrets first (see Rules), update your local `.env`,
and only then run `make push-env`.

Restore the databases (skip if you have none):
```
ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@ai-trader-vps \
  'mkdir -p /opt/ai-trading-agent/services/freqtrade/user_data && cd /opt/ai-trading-agent/services/freqtrade/user_data && tar xzf -' \
  < ~/vps-rebuild-backup/freqtrade-dbs.tgz
```
Expected: no output. Check with
`make ssh` then `ls -l /opt/ai-trading-agent/services/freqtrade/user_data/*.sqlite`,
which lists `tradesv3.dryrun.sqlite`.
(To restore from the off-host nightly backups instead, use
[`restore-backup.md`](restore-backup.md): Part A downloads and checks the
latest copies, Part B puts them back.)

### 8. Deploy and verify the app

```
make deploy
make logs-remote
```
Expected: `Container ai-trading-agent-freqtrade  Started`, then a log line
containing `Dry run is enabled`. Ctrl-C to leave. Then run
`provision-vps.md` step 22 (nothing listens publicly), and steps 24-29 and 31
(tailnet HTTPS, `tailscale serve`, the loopback check, the external scan, and a
backup-now proof). A rebuilt server is a new tailnet device: the dashboard URL's
hostname is the same only if the old device was removed from the tailnet first.

### 9. Wrap up

- `rm -rf ~/vps-rebuild-backup` once you have confirmed the restored
  database is in place and the stack is healthy.
- If this was a **drill**: record start time, end time, total minutes, and
  anything that surprised you in `docs/drills/` (work package 3A-6).
- If this was an **incident**: note what you saw and when in the audit
  log / a dated note, and check [`03-risk-register.md`](../03-risk-register.md)
  S7.
