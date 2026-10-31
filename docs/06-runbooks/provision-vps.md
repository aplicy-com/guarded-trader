# Runbook — Provision the VPS (first time)

**When to use:** creating the Hetzner VPS from nothing for the first time:
create, verify, lock down, deploy. To destroy and recreate an existing
VPS, use [`rebuild-vps.md`](rebuild-vps.md) instead.

**Decision record:** [`ADR-0011`](../05-adr/0011-vps-hosting-on-hetzner.md).
**Code:** [`infra/terraform/`](../../infra/terraform/), `Makefile` targets
`vps-*`, `ssh`, `push-env`, `deploy`, `logs-remote`.

**What you end with:** one Hetzner server, static public IPv4, **zero
public inbound ports**, reachable only over Tailscale, running the
Freqtrade dry-run stack.

**Rules while you do this:**
- Never paste a token or key into a file, a commit, or a chat. They go
  only into shell environment variables (step 4) and the password manager.
- Run every command from the repo root on your Mac unless a step says
  "on the VPS".
- If any "Expected" line does not match what you see, **stop** and go to
  Troubleshooting at the bottom. Do not continue past a mismatch.

## Before you start

1. You need all of these. Tick each one:
   - [ ] A Hetzner Cloud account with an empty project for this system.
   - [ ] Tailscale installed and signed in on this Mac, with MagicDNS on
         (Tailscale admin console → DNS → MagicDNS enabled).
   - [ ] `terraform` and `nmap` installed (`brew install terraform nmap`).
   - [ ] The SSH key pair `~/.ssh/ai_trader_vps` and
         `~/.ssh/ai_trader_vps.pub`, with a passphrase on the private key.
   - [ ] the password manager open, to store the Hetzner token.
2. Confirm the infra code is on `main` (`make deploy` ships `main`, not
   your working tree):
   ```
   git switch main
   git log --oneline -1 -- infra/terraform
   ```
   Expected: one commit line. If it prints nothing, the branch
   `feat/vps-infra` has not been merged yet. Merge it first, then
   continue.
3. Check your private key has a passphrase (this should ask for one):
   ```
   ssh-keygen -y -f ~/.ssh/ai_trader_vps > /dev/null
   ```
   Expected: a passphrase prompt, then no output. If it prints nothing
   and does **not** ask, the key has no passphrase. Stop and add one with
   `ssh-keygen -p -f ~/.ssh/ai_trader_vps`.

## Provision

4. Create the non-secret settings file:
   ```
   cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
   curl -4 https://ifconfig.me
   ```
   The `curl` prints your current public IPv4, for example `198.51.100.7`.
   Open `infra/terraform/terraform.tfvars` and set
   `admin_cidr = "198.51.100.7/32"` (your IP, with `/32`). Save. This file
   is git-ignored. Check:
   ```
   git status --short infra/terraform/terraform.tfvars
   ```
   Expected: **no output** (ignored). If it lists the file, stop.

5. Get the two secrets.
   - **Hetzner token:** Hetzner Console → your project → Security → API
     tokens → Generate API token → permission **Read & Write**. Copy it
     once and save it in the password manager now. Hetzner never shows it again.
   - **Tailscale auth key:** Tailscale admin console → Settings → Keys →
     Generate auth key. Set **Reusable: off**, **Ephemeral: off**,
     **Expiry: 1 day**. Copy it (starts with `tskey-auth-`). Do not save
     it anywhere: it works once.
     **Copy the secret key, not the key ID.** The secret is shown once,
     right after you click Generate. The key ID in the key list afterwards
     is not a key: with it, `tailscale up` fails on first boot and the
     server never joins the tailnet. `make vps-plan`/`vps-apply` refuse a
     value that does not start with `tskey-auth-`.

6. Put them in your shell (this terminal tab only). These two lines
   prompt silently, so the secrets never land in your shell history:
   ```
   read -rs "TF_VAR_hcloud_token?Hetzner token: "; export TF_VAR_hcloud_token; echo
   read -rs "TF_VAR_tailscale_authkey?Tailscale auth key: "; export TF_VAR_tailscale_authkey; echo
   ```
   (zsh syntax. In bash use `read -rsp "Hetzner token: " TF_VAR_hcloud_token`.)
   Check they are set without printing them:
   ```
   [ -n "$TF_VAR_hcloud_token" ] && [ -n "$TF_VAR_tailscale_authkey" ] && echo both-set
   ```
   Expected: `both-set`.

7. Preview what will be created:
   ```
   make vps-plan
   ```
   Expected, near the end: `Plan: 4 to add, 0 to change, 0 to destroy.`
   (an SSH key, a primary IP, a firewall, a server). Scroll up and check the
   firewall shows one inbound rule on port `22` from your `/32`. If you
   see any `destroy`, or `admin_cidr` is not your `/32`, stop.

8. Create it:
   ```
   make vps-apply
   ```
   Terraform asks `Do you want to perform these actions?` Type `yes`.
   Expected: `Apply complete! Resources: 4 added, 0 changed, 0 destroyed.`
   followed by an `ipv4 = "x.x.x.x"` output. This IP is permanent across
   rebuilds. Write it down: it is the Kraken whitelist IP later.

9. Wait for first-boot setup to finish. This takes 3–6 minutes. Save the
   IP in a variable, then wait:
   ```
   IP=$(terraform -chdir=infra/terraform output -raw ipv4)
   ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new deploy@$IP 'cloud-init status --wait'
   ```
   If you get `Connection refused` or `timed out`, the server is still
   booting. Wait 60 seconds and run the same command again.
   Expected: `status: done`.
   If it says `status: error`, go to Troubleshooting ("cloud-init
   failed").

## Verify the server (still over the public IP)

10. Run these on the VPS in one go:
    ```
    ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@$IP 'id; id -u deploy; docker --version; docker compose version; tailscale status | head -3; sudo sshd -T | grep -Ei "^(permitrootlogin|passwordauthentication|allowusers) "; sudo fail2ban-client status sshd | head -3; timedatectl | grep "Time zone"; swapon --show --noheading; ls -ld /opt/ai-trading-agent'
    ```
    Expected, in order:
    - `id` output contains `(sudo)` and `(docker)`
    - `1000` (the deploy user's uid; see Troubleshooting if it is not 1000)
    - `Docker version 2…` and `Docker Compose version v2…`
    - `tailscale status` lists `ai-trader-vps` with an address `100.x.x.x`
    - `permitrootlogin no`, `passwordauthentication no`, `allowusers deploy`
    - `Status for the jail: sshd`
    - `Time zone: Etc/UTC (UTC, +0000)`
    - a `/swapfile` line with `2G`
    - `drwxr-x--- … deploy deploy … /opt/ai-trading-agent`

11. Confirm the VPS joined your tailnet and you can reach it that way.
    On the Mac:
    ```
    tailscale status | grep ai-trader-vps
    make ssh
    ```
    Expected: a line with `ai-trader-vps` and `100.x.x.x`; then a shell
    prompt `deploy@ai-trader-vps:~$`. Type `exit`.
    **Do not lock down until this works.** After lockdown, this path is
    the only way in.

12. In the Tailscale admin console → Settings → Keys, revoke the auth key
    from step 5 (it is already used up; revoking is cleanup).

## Harden the host (tailnet-only SSH, before the cloud firewall lockdown)

12a. The Hetzner firewall alone is not trusted (incident S8 in
    [`03-risk-register.md`](../03-risk-register.md)). Add the host-level
    layer **over Tailscale** (the script refuses otherwise). Use the VPS's
    `100.x` address from `tailscale status` (for example `TS=100.101.102.103`):
    ```
    TS=100.101.102.103
    scp -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes scripts/harden-host.sh deploy@$TS:/tmp/
    ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@$TS 'sudo bash /tmp/harden-host.sh --dry-run --ssh-connection "$SSH_CONNECTION"'
    ```
    The dry run changes nothing. Expected: no `WOULD ABORT` lines and the
    last line `Dry run complete. Nothing was changed.` Then apply, keeping
    this terminal open:
    ```
    ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@$TS 'sudo bash /tmp/harden-host.sh --ssh-connection "$SSH_CONNECTION"'
    ```
    (`sudo` strips `SSH_CONNECTION`, which is why it is passed explicitly;
    with no valid tailnet connection the script stops and changes nothing.)
    Expected: `Applied.`, port 22 listeners only `100.x.x.x:22` and
    `127.0.0.1:22`, ufw `Status: active` with one rule
    `Anywhere on tailscale0 ALLOW IN`, and `AUTO-ROLLBACK in 300s`.

12b. **Within 5 minutes**, open a *second* terminal and run `make ssh`.
    Expected: the `deploy@ai-trader-vps` prompt. Only then confirm:
    ```
    ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@$TS 'sudo bash /tmp/harden-host.sh --confirm'
    ```
    Expected: `Confirmed: lockdown kept, rollback cancelled.` If the second
    terminal cannot connect, do nothing: after 5 minutes the rollback turns
    ufw off and puts `ssh.socket` back on all addresses.
    Why `ssh.socket`: Ubuntu 24.04 starts sshd from a systemd socket that
    owns port 22, so `ListenAddress` in `sshd_config` is ignored. The script
    overrides the socket's `ListenStream` (with `FreeBind=yes`, so it still
    binds at boot before Tailscale is up). It was chosen over disabling the
    socket because it keeps Ubuntu's default model and survives package
    upgrades.
    (A server created from the current cloud-init runs this same script
    at first boot with `--allow-public-ssh-from <admin_cidr>`, so ufw is
    already on and SSH is still reachable from `admin_cidr` for bootstrap;
    the steps above remove that last public path.)

## Lock down (remove public SSH)

13. Preview. Your shell still has the two `TF_VAR_` secrets from step 6.
    The Tailscale value is ignored from here on (the server is never
    re-created by a lockdown), but it must still be set and start with
    `tskey-`. If you opened a new terminal tab, set a placeholder:
    `export TF_VAR_tailscale_authkey=tskey-auth-unused` and re-run the
    `read` line for the Hetzner token.
    ```
    make vps-plan BOOTSTRAP=false
    ```
    Expected: `Plan: 0 to add, 1 to change, 0 to destroy.` and the change is
    `hcloud_firewall.vps` swapping its SSH `rule` for the inert sentinel
    rule (ICMP from `192.0.2.1/32`, which matches no real traffic). If it says anything about
    `hcloud_server.vps` being replaced or destroyed, **stop** and go to
    Troubleshooting ("lockdown wants to replace the server").

14. Apply:
    ```
    make vps-lockdown
    ```
    Type `yes`. Expected:
    `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.`
    and `bootstrap_ssh_open = false`.

## Verify zero public inbound

14a. Automated check (fails with exit 1 if TCP 22 on the public IP accepts
    a connection). Run it from a network that is **not** `admin_cidr` if
    possible, and with no Tailscale exit node selected:
    ```
    make verify-lockdown
    ```
    Expected: `OK: TCP 22 on <ip> does not accept connections`. Run it after
    **every** `make vps-lockdown`. `FAIL: ... ACCEPTS connections` is an
    incident: do not proceed, see Troubleshooting ("Public SSH still
    works after lockdown").

15. Public SSH must now fail:
    ```
    ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 deploy@$IP true
    ```
    Expected: `Connection timed out` (not `Permission denied`; a refusal
    would mean something is answering).

16. Tailscale SSH must still work:
    ```
    make ssh
    ```
    Expected: the `deploy@ai-trader-vps` prompt. Type `exit`.

17. External port scan. Use a different network from your usual one if
    you can (phone hotspot), and make sure no Tailscale exit node is
    selected (`tailscale status` shows `-` or no `exit node`). Then:
    ```
    nmap -Pn -p- -T4 $IP
    sudo nmap -Pn -sU --top-ports 100 $IP
    ```
    Expected, first scan, a line like:
    `All 65535 scanned ports on <ip> are in ignored states.` with
    `65535 filtered tcp ports (no-response)`.
    Expected, second scan: every port `open|filtered`, none `open`.
    **If any port shows `open`, stop and treat it as an incident:** run
    `make vps-lockdown` again, re-scan, and if it persists follow
    [`rebuild-vps.md`](rebuild-vps.md).
    Both scans cover port 8000 (the dashboard) and 443 (`tailscale serve`)
    too, so they must also show no `open` there once step 25 is done.
    Save the scan output (it is not secret) for the 3A exit gate
    ("zero public inbound ports verified").

## Deploy

18. Stop the Mac's dry-run so the same Telegram bot token is not polled
    from two places (that causes `Conflict: terminated by other
    getUpdates request` errors). On the Mac:
    ```
    make down
    ```
    Expected: `Container ai-trading-agent-freqtrade  Removed`.
    The VPS starts with a fresh dry-run database. The Mac's
    `services/freqtrade/user_data/tradesv3.dryrun.sqlite` stays on the Mac
    as the Phase 2 record; do not copy it over.

19. Check your local `.env` says `TRADING_MODE=dry_run`, then copy it:
    ```
    grep '^TRADING_MODE' .env
    make push-env
    ```
    Expected: `TRADING_MODE=dry_run`, then
    `pushed .env -> ai-trader-vps:/opt/ai-trading-agent/.env (root:deploy 0640)`.
    (The target refuses to push if `TRADING_MODE` is not `dry_run`.)
    Verify the file's owner and mode:
    ```
    make ssh
    ls -l /opt/ai-trading-agent/.env
    exit
    ```
    Expected: `-rw-r----- 1 root deploy … /opt/ai-trading-agent/.env`.

20. Deploy and start:
    ```
    make deploy
    ```
    Expected: rsync file list, then (first run pulls the image, ~1 minute)
    `Container ai-trading-agent-freqtrade  Started`.

21. Verify Freqtrade is running in dry-run:
    ```
    make logs-remote
    ```
    Expected, within about 30 seconds: a line containing
    `Dry run is enabled`. If you do not see it, **do not assume it is
    safe**: press Ctrl-C, run `make ssh` and
    `cd /opt/ai-trading-agent && docker compose -f infra/docker-compose.yml down`,
    then check `config.dry_run.json`. Press Ctrl-C to leave the logs.

22. Verify nothing listens publicly on the VPS itself:
    ```
    make ssh
    sudo ss -tlnp | grep -v '127\.0\.0\.\|\[::1\]'
    docker ps --format '{{.Names}}  {{.Ports}}'
    exit
    ```
    Expected: the `ss` output lists only `sshd` on port 22 (reachable only
    via the tailnet, because the firewall drops public traffic) and
    `tailscaled`. `docker ps` shows
    `ai-trading-agent-freqtrade  127.0.0.1:8080->8080/tcp` and
    `ai-trading-agent-conductor  127.0.0.1:8000->8000/tcp`. Any other
    `0.0.0.0:` mapping means stop and fix the compose file.

23. Record the VPS dry-run start time (UTC) wherever the Phase 2
    dry-run start was recorded, so Gate 2's clock is unambiguous.

## Dashboard, heartbeat and backups (work package 3A-5)

Decision records:
[`ADR-0017`](../05-adr/0017-read-only-dashboard-over-tailscale.md) (dashboard
and access), [`ADR-0016`](../05-adr/0016-backups-write-only-key-no-client-side-encryption.md)
(backups). On a VPS that was provisioned **before** 3A-5, do steps 24-31 by hand
(cloud-init only runs on first boot). On a fresh VPS cloud-init already tried
step 25 for you; still do 24 first, then check step 25 says it is applied.

24. Tailnet prerequisites (Tailscale admin console, in your browser):
    - **DNS → HTTPS Certificates → Enable.** `tailscale serve` needs it to get a
      certificate for `ai-trader-vps.<your-tailnet>.ts.net`.
    - **Access controls:** limit who can reach this server. Keep your existing
      rules for everything else, and make sure only **your own user's devices**
      can reach `ai-trader-vps` on TCP **22** and **443**. Use the console's
      *Preview rules* to check the result. (Details and the reasoning:
      [`security.md`](../04-architecture/security.md), "Tailnet access".)

25. Expose the dashboard to the tailnet only. On the VPS:
    ```
    make ssh
    sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
    sudo tailscale serve status
    sudo tailscale funnel status
    ```
    Expected, `serve status`: a line `https://ai-trader-vps.<tailnet>.ts.net`
    marked **(tailnet only)** and `|-- / proxy http://127.0.0.1:8000`. Expected,
    `funnel status`: **no** entry marked `(Funnel on)`. If anything says Funnel
    is on, run `sudo tailscale funnel reset` and stop: that would be public.
    (`--bg` makes it permanent: it survives reboots. To remove it:
    `sudo tailscale serve reset`.) Then `exit`.

26. Add the new values to your local `.env` (never anywhere else), then push:
    - `HEALTHCHECK_PING_URL`: in healthchecks.io create a check for this system with
      **Period 5 minutes, Grace Time 10 minutes** (so it alerts after about 15
      minutes of silence), add an alert channel that does not depend on the VPS or Conductor (email
      or the phone app; healthchecks.io's own Telegram integration is separate
      from Conductor's bot), and copy its ping URL.
    - `BACKUP_B2_BUCKET`, `BACKUP_B2_ENDPOINT`, `BACKUP_B2_KEY_ID`,
      `BACKUP_B2_APP_KEY`: the bucket and the **write-only** application key
      (limited to that bucket; lifecycle rule "delete after 30 days" set on the
      bucket). All four or none.
    ```
    make push-env
    make deploy
    ```
    Expected: `Container ai-trading-agent-conductor  Started`. Conductor refuses to
    start if only some of the four backup values are set; the message names the
    missing ones.

27. Prove the port really is loopback-only, on the VPS (this is the "Docker
    bypasses ufw" check):
    ```
    make ssh
    sudo ss -ltn 'sport = :8000'
    sudo iptables -t nat -S DOCKER | grep -- '--dport 8000'
    exit
    ```
    Expected: `ss` shows `127.0.0.1:8000` and **not** `0.0.0.0:8000` or `*:8000`;
    the iptables rule contains `-d 127.0.0.1/32`. A rule without `-d 127.0.0.1/32`,
    or a `0.0.0.0` listener, means stop and fix the compose file. Even if Docker
    did bypass ufw, the Hetzner Cloud Firewall (zero inbound rules) still drops
    public traffic before the host sees it; step 29 proves that from outside.

28. Open the dashboard from a device on your tailnet (Mac or phone):
    `https://ai-trader-vps.<your-tailnet>.ts.net/`
    Expected: the *Overview* page with principal `$100.00` and "No active halts".
    Check *Positions*, *Halts & audit*, *Strategies* and *Research* load.
    Then turn Tailscale **off** on that device (phone on mobile data) and reload:
    expected, the page does not load (it must not be reachable without the tailnet).

29. From outside, prove nothing new is public. Same conditions as step 17
    (different network, no Tailscale exit node):
    ```
    make verify-lockdown
    ```
    Expected: four `OK:` lines (TCP 22, 443, 8000 and 8080 do not accept
    connections) and exit status 0. Repeat the `nmap` scans from step 17 and keep
    the output for the 3A exit gate.

30. Prove the heartbeat. Wait about 6 minutes after the deploy, then check
    healthchecks.io: the check shows **up** with a recent ping. The dashboard's
    *Monitoring* box shows Heartbeat **ok**. (The silence drill, stopping the
    container and getting the alert after about 15 minutes, is part of 3A-6.)

31. Prove the backup, from the VPS, without waiting for 03:15 UTC:
    ```
    make ssh
    docker exec ai-trading-agent-conductor python -m conductor.cli backup-now
    exit
    ```
    Expected:
    ```
    conductor: ok backups/dry_run/conductor/conductor-<time>-<id>.sqlite.gz
    freqtrade: ok backups/dry_run/freqtrade/freqtrade-<time>-<id>.sqlite.gz
    ```
    If either says `FAILED`, read the reason and go to
    [`restore-backup.md`](restore-backup.md) Troubleshooting. Then prove the files
    are restorable: do **Part A of [`restore-backup.md`](restore-backup.md)** from
    your Mac. The write-only key cannot read the files back, so only that test proves
    the backup is usable. The dashboard *Monitoring* box now shows both backups ok.

32. Done.

## Later infra changes

Use `make vps-lockdown` for every later `terraform apply` (it keeps SSH
closed). Use `make vps-apply` only for a first provision or a deliberate
temporary re-open. Updating the app is `make deploy`; updating secrets is
`make push-env` then `make deploy`.

## Troubleshooting

- **`cloud-init failed` (step 9 says `status: error`).** Read why:
  `ssh -i ~/.ssh/ai_trader_vps -o IdentitiesOnly=yes deploy@$IP 'sudo tail -60 /var/log/cloud-init-output.log'`.
  Usual causes: Docker or Tailscale apt repo unreachable (retry later).
  Fix by rebuilding: [`rebuild-vps.md`](rebuild-vps.md) step "Recreate"
  (needs a **new** Tailscale auth key, since the first was probably
  consumed).
- **The server never appears in `tailscale status`.** The auth key was
  wrong, expired, or already used (the most common mistake: the key ID was
  pasted instead of the `tskey-auth-...` secret). Confirm on the server:
  `sudo grep -A5 "CLOUD-INIT ERROR" /var/log/cloud-init-output.log`; a
  failed join prints a boxed `CLOUD-INIT ERROR: 'tailscale up' FAILED`
  message there. Do not lock down. Rebuild with a new
  key ([`rebuild-vps.md`](rebuild-vps.md)).
- **`id -u deploy` is not 1000.** The Freqtrade container runs as uid 1000
  and writes into the deployed `user_data/` directory. Fix on the VPS:
  `sudo chown -R 1000:1000 /opt/ai-trading-agent/services/freqtrade/user_data`
  after the first `make deploy`, and tell the next session so cloud-init
  can be fixed.
- **`terraform apply` error mentioning the server type or location.**
  `cx23` may not be orderable in `nbg1` right now. Set a different
  `location` (`fsn1` or `hel1`) in `terraform.tfvars` and re-run
  `make vps-plan`. Do not switch to a non-`cx` type without updating
  ADR-0011.
- **Lockdown wants to replace the server.** Never apply that. It means
  something other than the firewall differs. Cancel at the prompt (type
  anything but `yes`), and check `git diff infra/terraform`.
- **Public SSH still works after lockdown (`make verify-lockdown` fails).**
  1. Read the firewall as Hetzner sees it (read-only):
     `curl -s -H "Authorization: Bearer $TF_VAR_hcloud_token" https://api.hetzner.cloud/v1/servers/<id from terraform state show hcloud_server.vps> | jq '.server.public_net.firewalls'`
     Expected: one entry with `"status": "applied"`. `pending` or an empty
     list means the firewall is not enforced.
  2. Then `curl ... /v1/firewalls/<id> | jq '.firewall.rules'`. Expected after
     lockdown: only the ICMP sentinel from `192.0.2.1/32`; a `port: "22"`
     rule means lockdown did not apply.
  3. Whatever you find, the host layer still protects you if
     `scripts/harden-host.sh` was run (step 12a). If it was not, run it now.
  4. Also check `ssh -G` / `~/.ssh/config` for `ControlMaster`/`ControlPersist`
     or a ProxyCommand: a multiplexed or tunnelled connection makes a
     "public IP" test succeed without touching the public network.
- **Locked out after lockdown (Tailscale is down on the VPS).** SSH is no
  longer reachable on the public IP at all (cloud firewall and host
  firewall both block it). Use the Hetzner Cloud web console (server →
  Console, log in as `deploy` is impossible without a password) or the
  rescue system to fix Tailscale/ufw; or simply rebuild:
  [`rebuild-vps.md`](rebuild-vps.md). To use the public IP temporarily,
  set `admin_cidr`, run `make vps-apply`, **and** on the host
  `sudo ufw allow from <cidr> to any port 22 proto tcp` plus remove
  `/etc/systemd/system/ssh.socket.d/20-tailscale-only.conf`, run
  `sudo systemctl daemon-reload && sudo systemctl stop ssh.service ssh.socket && sudo systemctl start ssh.socket`; then repeat the lockdown steps.
- **`Host key verification failed` after a rebuild.** Expected: the new
  server has a new host key. Remove the old entry:
  `ssh-keygen -R ai-trader-vps` and `ssh-keygen -R $IP`.
