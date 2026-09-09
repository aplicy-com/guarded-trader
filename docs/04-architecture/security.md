# Architecture — Security

Threat model for this project is dominated by two asset classes: the
Kraken API key (money-adjacent) and the host itself (everything else runs
on it). Scope is intentionally narrow — this is a $100, single-operator
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

- Local development/runtime: `.env` file (git-ignored), or OS
  keychain/1Password for anything longer-lived.
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

- No inbound public ports on the trading host for Phase 1–4.
- Remote access (to check status, SSH in, or reach the Conductor API from
  elsewhere) via [Tailscale](https://tailscale.com/) rather than exposing
  anything publicly. **Not yet installed** (confirmed 2026-09-09: no
  `tailscale` CLI on the current Mac host) — this is a manual device
  action (install on the Mac + phone, per `docs/phase-2-plan.md` §1), not
  a docs decision, so it isn't "resolved" by this closure pass. Not
  blocking the Phase 2 exit gate: the local dry-run/heartbeat model
  (NFR4) doesn't depend on remote access, only convenience does. Complete
  before relying on remote monitoring for real.
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

- OS auto-updates enabled (risk register S3).
- Minimal installed software — the host runs Docker and little else.
- Full-disk encryption (FileVault on Mac; LUKS on the future mini-PC) —
  confirmed On (`fdesetup status`, 2026-09-09), see risk register S6.
- Sleep/power-nap disabled while the trading stack is expected to be
  running (risk register O1) — mechanism is Amphetamine (an always-on
  login session kept awake with the lid closed), not `pmset`/`caffeinate`;
  see [`../../infra/README.md`](../../infra/README.md#sleep-disable-mac-host).

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
| Exchange API key/secret | Critical | `.env` / 1Password only |
| Telegram bot token | Critical | `.env` / 1Password only |
| Anthropic API key | High | `.env` / 1Password only |
| Ledger (fills, balances, P&L) | High (financial, tax-relevant) | Ledger DB, host-local, encrypted at rest |
| Strategy code | Medium (IP-adjacent, but repo is open-source by design) | Git, public |
| LLM prompts/responses | Medium (may reference strategy internals) | Ledger DB |
| Docs (this repo) | Public by design | Git, public |

## TBD

- Tailscale ACL details — TBD, blocked on Tailscale actually being
  installed first (operator action, see "Network" above; not yet done).
- ~~Pre-commit secret-scanning tool~~ — resolved: gitleaks.
- ~~Disk-encryption verification~~ — resolved: FileVault confirmed On, see
  "Host hardening" above.
- Dependency-update automation tool — re-tagged TBD (Phase 3): there is
  no GitHub remote and no dependency manifest file in this repo yet
  (confirmed 2026-09-09) — nothing exists to point Dependabot/Renovate at.
  The only "dependency" at repo scope today is the pinned Freqtrade Docker
  image tag, already governed by the deliberate-bump policy in
  `infra/docker-compose.yml`'s own comment. Revisit once Phase 3
  introduces real Python package dependencies for Conductor.
