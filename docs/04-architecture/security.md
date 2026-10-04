# Architecture — Security

Threat model for this project is dominated by two asset classes: the
Kraken API key (money-adjacent) and the host itself (everything else runs
on it). From Phase 3 the host is a Hetzner VPS
([ADR-0011](../05-adr/0011-vps-hosting-on-hetzner.md)); the Mac is
dev-only. See "VPS threat model" below. Scope is intentionally narrow — this is a $100, single-operator
system, not an enterprise deployment — but the controls below are treated
as non-negotiable regardless of principal size (see `CLAUDE.md` §0).

## Exchange key scope

| Property | Required value |
|---|---|
| Query Funds | Enabled |
| Query Open/Closed Orders | Enabled |
| Query Ledger Entries | Enabled |
| Create/Modify/Cancel Orders | Enabled |
| **Withdraw Funds** | **Disabled — always** |
| IP whitelist | Enabled, restricted to the trading host's static/known egress IP |

This mirrors NFR2/AC1.3 and risk register S2. Verified at key creation and
at every rotation — see
[`06-runbooks/key-rotation.md`](../06-runbooks/key-rotation.md). Deposits
and withdrawals to/from the trading account are exclusively manual, human,
out-of-band actions (R1 AC1.3) — no code path in this repo is capable of
initiating one.

## Secrets management

- **LastPass is the system of record** for every secret (exchange key,
  Telegram tokens, Anthropic key, Hetzner API token, Tailscale keys).
- Local development: `.env` file (git-ignored) on the Mac.
- VPS runtime: `/opt/ai-trading-agent/.env`, mode `0640`, owner
  `root:deploy` (the deploy user's `docker compose` must read it; nobody
  else can). Copied from the Mac's `.env` by `make push-env`, which
  streams over SSH and never leaves a world-readable temp file. It is
  excluded from `make deploy`'s rsync, so a deploy cannot overwrite or
  delete it.
- Terraform secrets (`TF_VAR_hcloud_token`, `TF_VAR_tailscale_authkey`)
  exist only as shell environment variables. Never in a tfvars file,
  never in the repo. `terraform.tfvars` holds non-secret values only and
  is git-ignored.
- `.env.example` documents the shape of required config with empty values
  only — see [`../../.env.example`](../../.env.example).
- No secret is ever logged. Log statements involving credentials must log
  presence/absence and key-id/fingerprint only, never the secret value.
- Pre-commit secret scanning — tool choice TBD (Phase 2, candidates:
  `gitleaks`, `git-secrets`).
- Before any push to a public remote, a manual review pass confirms no
  secret, account number, or balance is present in tracked files
  (`CLAUDE.md` §5).

## Network

- No inbound public ports on the trading host for Phase 1–4. On the VPS
  this is enforced by a Hetzner Cloud Firewall with **zero inbound rules**
  once `make vps-lockdown` has run (a bootstrap-only SSH rule from one
  `admin_cidr` exists during first provisioning). The firewall sits outside
  the host, so Docker's iptables rules cannot bypass it. Containers publish
  ports on `127.0.0.1` only. Verified by an external `nmap` scan
  ([`provision-vps.md`](../06-runbooks/provision-vps.md) step 17).
- Remote access (SSH, Conductor API, dashboard) is via
  [Tailscale](https://tailscale.com/) only. The VPS joins the tailnet as
  `ai-trader-vps` at first boot. Tailscale SSH is off; plain OpenSSH
  (key-only, `deploy` user only) is used over the tailnet.
  Because the firewall allows no inbound UDP, Tailscale connections fall
  back to relayed (DERP) paths when a direct path cannot be punched
  through; that is slower but works, and is acceptable for this workload.
- Telegram is the only outbound-initiated, internet-facing control
  surface, and it is chat-ID allow-listed (see
  [`conductor.md`](conductor.md)).
- Kraken, Anthropic, and heartbeat (healthchecks.io) API calls are all
  outbound-only from the host; no inbound webhook or polling endpoint is
  required anywhere in the current design — this includes health/liveness
  monitoring, which uses a push (dead-man's-switch) model specifically so
  the host never has to expose anything to be watched (see
  `conductor.md`).

## Host hardening

**VPS** (configured by `infra/terraform/cloud-init.yaml.tftpl`):

- `unattended-upgrades` on, with an automatic reboot at 05:30 UTC when a
  kernel update needs one (risk register S3).
- Minimal installed software: Docker Engine + compose plugin (Docker's
  official apt repo), Tailscale, `fail2ban`, `rsync`.
- SSH: `PermitRootLogin no`, `PasswordAuthentication no`,
  `AllowUsers deploy`, `MaxAuthTries 3`. `fail2ban` `sshd` jail on
  (never bans loopback or the tailnet range).
- No full-disk encryption (see S6 and ADR-0011: Hetzner Cloud offers no
  customer-controlled at-rest encryption, and LUKS would block unattended
  reboots).
- Docker log rotation (10 MB x 3) so logs cannot fill the 40 GB disk.

**Mac** (dev machine only from Phase 3): FileVault On (`fdesetup status`,
confirmed 2026-09-09). The Mac holds the SSH private key and the master
`.env`, so it remains in scope for S1/S3. The earlier sleep-disable
measure (Amphetamine, risk register O1) is no longer needed for
trading.

## Telegram control-surface auth

- Bot token treated as a secret (never committed, rotated per
  [`key-rotation.md`](../06-runbooks/key-rotation.md)).
- Every incoming command checked against `TELEGRAM_ALLOWED_CHAT_IDS`
  before execution; unauthorized senders are logged and ignored, not
  replied to with any system detail.
- All commands (`/kill`, `/flatten`, `/resume`, `/approve`) are logged in
  the ledger with sender identity and timestamp (AC4.6).
- By design, every command an unauthorized party could send is either a
  no-op or *reduces* risk (kill, flatten) — there is no Telegram command
  that can raise exposure, change `max_deployed_capital`, or export a
  secret.

## VPS threat model

Assets on the VPS: `.env` (future exchange key, Telegram and Anthropic
secrets), the ledger and Freqtrade databases, and the ability to place
orders through Freqtrade. The exchange key never has withdrawal
permission, so even full host compromise cannot move funds out of the
exchange account. It can trade that key's account until the key is
revoked.

| Threat | Control | Residual risk |
|---|---|---|
| Internet scanning / brute force of SSH | Zero public inbound (firewall); key-only SSH; `fail2ban` | None on the public interface after lockdown. During bootstrap, SSH is reachable only from one `/32`. |
| Stolen SSH key | Passphrase on the key; host reachable only over the tailnet, so the key alone is not enough | Key plus a tailnet seat is root-equivalent (`deploy` has passwordless sudo and `docker`). Revoke the key by rebuild ([`rebuild-vps.md`](../06-runbooks/rebuild-vps.md)). |
| Tailscale account takeover | Tailscale account has MFA (operator action, verify); device approval | A takeover could add a device to the tailnet. Tailscale ACLs: TBD (Phase 3), to be written before Conductor's dashboard is exposed. |
| Hetzner account or API token compromise | Token held in LastPass, in env only during a run; Hetzner account MFA (operator action, verify) | Attacker can rebuild/delete the server, or read its disk. Revoke the token; rotate every secret on the box. |
| Provider (Hetzner) staff or hypervisor access | Key is trade-only, no withdrawal, IP-whitelisted; $100 principal | Accepted (ADR-0011). Disk not encrypted at rest. |
| Terraform state leak | State is local and git-ignored; the Tailscale key in it is single-use and expired; no remote backend | State also reveals the server layout; treat as secret anyway (risk register S8). |
| Tailscale auth key exposure via user-data / metadata service | Single-use, 1-day expiry, revoked after join; cloud-init deletes local copies | The metadata endpoint is reachable from containers. Harmless once the key is consumed. Blocking `169.254.169.254` from containers is a possible later hardening, not done in 3A-0. |
| Compromised container (Freqtrade, later candidate code) | Containers publish loopback ports only; candidate code runs in `network=none` sandboxes (ADR-0007); no Docker socket mounted | A container escape reaches the host. Same class of risk as any Docker host. |
| Supply chain (apt, Docker, Tailscale repos) | Official signed repos only; image tags pinned | First boot trusts the repo keys fetched over HTTPS. |
| Unpatched host | `unattended-upgrades` with auto-reboot | Short window between disclosure and patch. |
| Provider outage | See risk register O7 | Paper trading and research pause. |

## Candidate code execution (LLM-generated strategy code)

LLM-generated strategy code is a distinct trust boundary from order
placement (`ADR-0003`) and is treated as **untrusted code**, not merely
untrusted judgement, until it passes admission
([`ADR-0007`](../05-adr/0007-candidate-code-admission.md),
`conductor.md`):

- **Static analysis first** — import whitelist enforced; `os`,
  `subprocess`, `socket`, `requests` (and equivalents), and any
  file-write operation are forbidden and cause automatic rejection before
  any execution takes place.
- **Sandboxed execution** — a candidate's backtest and walk-forward run
  inside a throwaway, network-disabled container with no exchange
  credentials, no secrets, and no access to the ledger DB — nothing in
  that container is worth exfiltrating even if static analysis missed
  something.
- **Human approval** — a strategy version containing LLM-generated code
  never reaches paper trading, let alone live capital, without an
  explicit, logged `/approve` from an allow-listed operator (see
  `conductor.md`).

This treats "the LLM produced this code" as a security event requiring
containment, not merely a quality question resolved by backtesting.

## Supply chain

- Dependencies pinned with a lockfile (Freqtrade, Conductor's Python
  deps); automated update alerts (Dependabot or equivalent — TBD Phase
  2); diffs reviewed before accepting an upgrade, especially for anything
  with exchange or network access (risk register S5).
- Docker base images pinned to specific tags/digests, not `latest`.

## Data classification

| Data | Sensitivity | Where it lives |
|---|---|---|
| Exchange API key/secret | Critical | LastPass; `.env` on Mac and VPS only |
| Telegram bot token | Critical | LastPass; `.env` on Mac and VPS only |
| Anthropic API key | High | LastPass; `.env` on Mac and VPS only |
| Hetzner API token | Critical (full control of the project: can delete or rebuild the server) | LastPass; shell env during a Terraform run only |
| SSH private key (`~/.ssh/ai_trader_vps`) | Critical (root-equivalent on the VPS, given tailnet access) | Mac only, passphrase-protected |
| Terraform state | High (contains the rendered cloud-init) | Mac only, git-ignored, never pushed |
| Ledger (fills, balances, P&L) | High (financial, tax-relevant) | Ledger DB, host-local (VPS disk is not encrypted at rest, see ADR-0011); off-host backup TBD (3A-5) |
| Strategy code | Medium (IP-adjacent, but repo is open-source by design) | Git, public |
| LLM prompts/responses | Medium (may reference strategy internals) | Ledger DB |
| Docs (this repo) | Public by design | Git, public |

## TBD

- Tailscale ACL details — TBD (Phase 3), to be written before Conductor's
  dashboard is exposed on the tailnet. Tailscale itself is installed on
  the VPS by cloud-init; the operator's Mac and phone are operator actions.
- Blocking container access to the cloud metadata endpoint — TBD (Phase 3,
  optional hardening).
- ~~Pre-commit secret-scanning tool~~ — resolved: gitleaks.
- ~~Disk-encryption verification~~ — resolved for the Mac (FileVault On).
  The VPS has no at-rest encryption by decision, see ADR-0011.
- Dependency-update automation tool — re-tagged TBD (Phase 3): there is
  no GitHub remote and no dependency manifest file in this repo yet
  (confirmed 2026-09-09) — nothing exists to point Dependabot/Renovate at.
  The only "dependency" at repo scope today is the pinned Freqtrade Docker
  image tag, already governed by the deliberate-bump policy in
  `infra/docker-compose.yml`'s own comment. Revisit once Phase 3
  introduces real Python package dependencies for Conductor.
