# ADR-0011: VPS hosting on Hetzner, reachable only over Tailscale

## Status

Accepted — 2026-10-04. Supersedes [ADR-0004](0004-mac-first-minipc-later.md).

## Context and problem statement

ADR-0004 put the stack on the operator's Mac for Phases 1–2 and planned a
migration to a dedicated mini-PC. Phase 2 ran that way, and Phase 3
changes the load: Conductor (always-on API, scheduler, Telegram bot,
dashboard), up to three parallel Freqtrade dry-run containers
([`phase-3-plan.md`](../phase-3-plan.md) D13), and a nightly LLM research
loop. That needs a host that is always on, has a static egress IP for the
future Kraken API-key whitelist (risk register S2), and can be rebuilt
from nothing. The Mac sleeps, travels, has a dynamic IP, and is shared
with unrelated work (risk register O1). A mini-PC would fix power and
sleep but still needs hardware, a home-network IP that can change, and a
physical location to lose.

ADR-0004 rejected a cloud VM because it is "a third-party host with
network access to exchange-adjacent secrets". This ADR revisits that and
accepts the trade-off, with the controls below.

## Decision drivers

- Always on, independent of the operator's laptop (O1).
- Static IPv4 for the Kraken key whitelist.
- Zero public attack surface: nothing to scan, nothing to brute-force.
- Rebuildable from zero by a runbook, not by memory (O4).
- Cost small relative to a $100 principal (~€5/month; see
  `phase-3-plan.md` §4 for the honest cost framing).
- The exchange key never has withdrawal permission (`CLAUDE.md` §0.2), so
  a compromised host's blast radius is bounded to trading that key.

## Considered options

- **Hetzner Cloud (`cx23`, Ubuntu 24.04, `nbg1`), Terraform + cloud-init,
  Tailscale-only access**
- Stay on the Mac (ADR-0004 status quo)
- Dedicated mini-PC at home (ADR-0004's end state)
- A US-region cloud VM (Hetzner `cpx` line, or another provider)

## Decision outcome

Chosen option: **Hetzner Cloud, EU, provisioned with Terraform
(`infra/terraform/`) and cloud-init, accessed only over Tailscale.**

- **Server:** `cx23` (2 vCPU, 4 GB RAM, 40 GB disk), Ubuntu 24.04 LTS,
  location `nbg1`, one static primary IPv4 (IPv6 disabled). The primary IP
  is a separate Terraform resource with `auto_delete = false`, so
  replacing the server keeps the address.
- **Server type deviation from the plan:** `phase-3-plan.md` D1 says
  `CX22`. Hetzner stopped offering `cx22` for new orders on 2026-01-01
  (changelog entry of 2025-10-16, "Old Server Types with shared vCPUs are
  deprecated") and its successor `cx23` has the same 2 vCPU / 4 GB / 40 GB
  shape, so `cx23` is used. `server_type` is a Terraform variable. Whether
  `cx23` is orderable in `nbg1` is confirmed by `terraform apply` itself,
  not by this ADR.
- **Network:** a Hetzner Cloud Firewall is the only public-facing control.
  During bootstrap it allows TCP 22 from one `admin_cidr` (a `/32`;
  `0.0.0.0/0` is rejected by variable validation). After Tailscale is up,
  `make vps-lockdown` applies `bootstrap_ssh=false`, which removes the
  rule: **zero public inbound**. The firewall is applied outside the host,
  so Docker's own iptables rules cannot bypass it. Containers publish
  ports on loopback only.
- **Access:** normal OpenSSH to the `deploy` user over the tailnet
  (`ssh deploy@ai-trader-vps`). Tailscale SSH is deliberately off
  (`--ssh=false`); one SSH mechanism to audit. Root login and password
  auth are disabled; `fail2ban` and `unattended-upgrades` are on.
- **Secrets:** Terraform secrets (`TF_VAR_hcloud_token`,
  `TF_VAR_tailscale_authkey`) exist only as shell environment variables.
  Application secrets live in `/opt/ai-trading-agent/.env`, mode `0640`,
  owner `root:deploy`, copied by `make push-env` from the operator's local
  `.env`. The password manager is the system of record for every secret.
- **Deploy:** `make deploy` ships the committed state of `main`
  (`git archive`) by rsync over Tailscale, then `docker compose up -d`.
  No CI/CD yet.
- **State:** Terraform state is local and git-ignored. It contains the
  rendered cloud-init (including the Tailscale auth key), so it is
  treated as a secret file (risk register S8).

### Consequences

**Good:**
- O1 (sleep/power) is retired as a host problem; heartbeat monitoring
  remains for process/network failure.
- Static IP for the Kraken whitelist; survives a server rebuild.
- Nothing on the public internet answers: no open port to attack, and
  admin access needs both the SSH key and tailnet membership.
- The whole host is reproducible: `rebuild-vps.md` is a drilled procedure.
- Mac becomes dev-only.

**Bad / accepted trade-offs:**
- **The provider can read the disk and RAM.** Hetzner Cloud offers no
  at-rest encryption we control, so `.env` (including the future Kraken
  key) is readable by anyone with hypervisor access. Accepted because the
  key is trade-only with no withdrawal permission and IP-whitelisted, and
  the principal is $100. Full-disk encryption (LUKS) is not used: it would
  need a manual unlock after every reboot, defeating unattended recovery.
  Risk register S6 is updated accordingly.
- **`deploy` is root-equivalent** (passwordless sudo and `docker` group).
  Whoever holds the SSH key and a tailnet seat owns the box. The private
  key therefore stays on the Mac only and passphrase-protected.
- **Single-provider, single-host.** A Hetzner outage or account problem
  stops paper trading and the research loop (risk register O7). Acceptable
  in Phase 3 (paper only). Must be re-assessed against open live
  positions before Phase 4: exchange-side stop-losses and the
  `rebuild-vps.md` recovery time are the relevant mitigations.
- **The Tailscale auth key transits Hetzner's user-data service.** It is
  single-use and short-lived by procedure (see `provision-vps.md`), so it
  is already consumed by the time anyone could read it; cloud-init also
  deletes its local copies. Containers can reach the metadata endpoint
  (`169.254.169.254`); blocking that is not done in 3A-0 and is tracked in
  the threat model in `security.md`.
- **Automatic reboots** at 05:30 UTC for kernel updates (mid-candle on the
  4h timeframe). Containers use `restart: unless-stopped`.
- Monthly cost (~€5) is a fixed drag on a $100 principal.

## More information

- **TBD (Phase 3, before work package 2E / Kraken key creation):** the
  operator is a Canadian resident, and the VPS egresses from a German
  datacenter IP. Whether Kraken permits API access (and an IP whitelist
  entry) from an EU datacenter address for a Canadian-resident account is
  not established by anything in this repo. Confirm with Kraken support
  before creating the key; if not permitted, this ADR's location choice
  is revisited (a US/CA region costs roughly 2× on the `cpx` line,
  `phase-3-plan.md` D1).
- Backups (ledger and Freqtrade DBs off-host) are `phase-3-plan.md` D6 /
  work package 3A-5, not part of this ADR. Until then, `rebuild-vps.md`
  restores configuration but not trading history.
- Related: [`provision-vps.md`](../06-runbooks/provision-vps.md),
  [`rebuild-vps.md`](../06-runbooks/rebuild-vps.md),
  [`security.md`](../04-architecture/security.md).
