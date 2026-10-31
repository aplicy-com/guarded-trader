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

For the live pilot (ADR-0019) the same table applies, with Query Ledger Entries optional, and
the IP is the VPS's primary IPv4 (`<VPS_STATIC_IP>`, `KRAKEN_EXPECTED_IP` in `.env`). The key is handed to the `freqtrade` container
only (`infra/docker-compose.live.yml`; never `conductor`, and blank in the dry-run stack), and
`scripts/kraken-access-check.sh` verifies the scopes behaviourally from the VPS: it expects
"permission denied" on deposit and withdraw lookups and fails otherwise.

This mirrors NFR2/AC1.3 and risk register S2. Verified at key creation and
at every rotation — see
[`06-runbooks/key-rotation.md`](../06-runbooks/key-rotation.md). Deposits
and withdrawals to/from the trading account are exclusively manual, human,
out-of-band actions (R1 AC1.3) — no code path in this repo is capable of
initiating one.

## Secrets management

- **the password manager is the system of record** for every secret (exchange key,
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
- The Conductor dashboard is read-only and is published on host loopback
  (`127.0.0.1:8000`) only; `tailscale serve` exposes it over HTTPS to the
  tailnet. Docker's published ports bypass ufw, so ufw is **not** what protects
  it: the compose bind to loopback and the Cloud Firewall above do, and
  `provision-vps.md` step 27 and `make verify-lockdown` check both
  ([`ADR-0017`](../05-adr/0017-read-only-dashboard-over-tailscale.md)).
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
- Long polling only (outbound HTTPS); no webhook, no inbound port. The
  token is passed to the conductor container only, and is redacted from
  Conductor's logs (the token sits in the request URL).
- Every write (`/kill`, `/flatten`, `/resume`) needs a second step: a random
  4-character code that the same chat must send back as `yes <code>` within
  60 s. A wrong code, a late answer, or a different chat does nothing, and a
  code cannot be replayed.
- All writes are logged in the ledger with the sender's chat ID as operator
  identity and a timestamp (AC4.6).
- There is no Telegram command that opens or sizes a trade, changes
  `max_deployed_capital` or exports a secret. Two commands reduce risk (kill,
  flatten). **`/resume` does the opposite**: it clears a halt and lets
  Freqtrade enter again, so it is the command that matters if the token or an
  allow-listed account is compromised. Its protections are the allowlist and
  the confirmation step; a breach that is still true re-halts within a minute.
- Freqtrade's own Telegram bot is disabled (ADR-0015), so its `/forceexit`,
  `/stop` and `/reload_config` are no longer reachable from chat.

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
| Tailscale account takeover | Tailscale account has MFA (operator action, verify); device approval; ACL limiting `ai-trader-vps` to your own devices on 22 and 443 (see "Tailnet access") | A takeover could add a device to the tailnet and read the dashboard (P&L, positions, audit log). It is read-only: nothing on it can trade or change state. |
| Backup key stolen from the VPS | The B2 application key is write-only (and should be limited to the one bucket): it can add files, not read, list or delete them; 30-day lifecycle; uploads use fresh unique keys | An attacker can fill the bucket with junk (cost, and noise in the 30-day window). Backups contain trade history, not secrets ([`ADR-0016`](../05-adr/0016-backups-write-only-key-no-client-side-encryption.md)). |
| Backblaze account takeover | MFA on the Backblaze account (operator action); SSE-B2 on the bucket; bucket private | Backups are not client-side encrypted (ADR-0016): an attacker with account access reads trade history and fence figures. No API keys or seed phrases are in them. |
| Dashboard misused as a write path | GET-only routes, no forms, tests that fail if a write route or form appears; strict CSP; all writes remain on Telegram with confirmation | None known; re-check when 3B adds pages. |
| Hetzner account or API token compromise | Token held in the password manager, in env only during a run; Hetzner account MFA (operator action, verify) | Attacker can rebuild/delete the server, or read its disk. Revoke the token; rotate every secret on the box. |
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
| Exchange API key/secret | Critical | Password manager; `.env` on Mac and VPS only |
| Telegram bot token | Critical | Password manager; `.env` on Mac and VPS only |
| Anthropic API key | High | Password manager; `.env` on Mac and VPS only |
| Hetzner API token | Critical (full control of the project: can delete or rebuild the server) | Password manager; shell env during a Terraform run only |
| SSH private key (`~/.ssh/ai_trader_vps`) | Critical (root-equivalent on the VPS, given tailnet access) | Mac only, passphrase-protected |
| Terraform state | High (contains the rendered cloud-init) | Mac only, git-ignored, never pushed |
| Ledger (fills, balances, P&L) | High (financial, tax-relevant) | Ledger DB, host-local (VPS disk is not encrypted at rest, see ADR-0011); off-host nightly backup to B2 ([`ADR-0016`](../05-adr/0016-backups-write-only-key-no-client-side-encryption.md)) |
| Strategy code | Medium (IP-adjacent, but repo is open-source by design) | Git, public |
| LLM prompts/responses | Medium (may reference strategy internals) | Ledger DB |
| Docs (this repo) | Public by design | Git, public |

## Tailnet access

Operator action, done in the Tailscale admin console (Access controls) before
exposing the dashboard ([`provision-vps.md`](../06-runbooks/provision-vps.md)
step 24). The intent, not a copy-paste policy (your tailnet's other rules must
keep working; use the console's *Preview rules*): only **your own user's
devices** may reach `ai-trader-vps`, and only on **TCP 22** (SSH) and **TCP 443**
(the dashboard via `tailscale serve`). Nothing else on the VPS should be
reachable over the tailnet. As a sketch of the shape (host alias, then a rule),
with the `100.x.y.z` replaced by the VPS's address from `tailscale status`:

```json
"hosts": { "ai-trader-vps": "100.x.y.z" },
"acls": [
  { "action": "accept", "src": ["autogroup:member"], "dst": ["ai-trader-vps:22,443"] }
]
```

After a VPS rebuild the server is a new tailnet device with a **new** `100.x`
address, so the `hosts` alias above must be updated to it
([`rebuild-vps.md`](../06-runbooks/rebuild-vps.md) step 6b); otherwise the rule
no longer matches the new server (and could match an unrelated device that is
later given the old address).

`autogroup:member` is every user in the tailnet; if other people are in it,
replace it with your own user. `tailscale funnel` (public) must never be enabled
for this host (`provision-vps.md` step 25 checks).

## TBD

- Tailscale itself is installed on the VPS by cloud-init; the operator's Mac and
  phone are operator actions. The ACL itself is verified by hand (above), not by
  code — TBD (Phase 3, 3A-6 drill) whether to check it from a second device.
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
