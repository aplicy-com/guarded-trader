# Runbook — Migrate from Mac to mini-PC

**Context:** per [`ADR-0004`](../05-adr/0004-mac-first-minipc-later.md),
the system starts on the operator's Mac and migrates to a dedicated,
always-on mini-PC once the reliability trade-off favours it. This runbook
is written ahead of that migration (Phase 4) so the procedure exists
before it's needed under time pressure — some steps have TBD specifics to
fill in when the mini-PC is actually provisioned.

**Principle for the whole migration:** the system should never be running
in two places at once believing it's the sole source of truth. Old host
stays authoritative and running until the new host is verified working in
dry-run; only then does live trading move over, with an explicit,
observed handoff — never a "start the new one and hope the old one
noticed."

## Before you start

1. Confirm current system state via [`start-stop.md`](start-stop.md) /
   `/status` — ideally, migrate when no positions are open (plan the
   timing around this if possible; not always avoidable if the system is
   halted for review anyway).
2. Provisioning checklist for the new mini-PC — TBD (Phase 4), expected to
   include at minimum:
   - OS installed, auto-updates enabled.
   - Full-disk encryption enabled (LUKS or equivalent) — see risk
     register S6.
   - Docker installed.
   - Tailscale installed and joined to the same network as before
     (`docs/04-architecture/security.md`).
   - Sleep/power-nap disabled; ideally a UPS in place (research review §4
     mentions this as a Phase 4 consideration).
   - NTP time sync confirmed working (risk register E5).

## Migration steps

1. On the **old host (Mac)**, engage the [kill switch](kill-switch.md) —
   no new positions should open during migration, though existing ones
   continue to be managed by the still-running Freqtrade instance there.
2. Back up everything that needs to move:
   - Ledger DB — export/dump per the mechanism decided in Phase 3 (TBD).
   - `.env` file — copy via a secure channel (not email, not Slack; use
     something like an encrypted 1Password note or `scp` over Tailscale),
     never committed to git.
   - Any Freqtrade `user_data/` state not already in git (git-ignored
     runtime state like the local SQLite DB, if used — check
     `.gitignore`).
3. On the **new host (mini-PC)**, clone the repo:
   ```
   git clone <repo-url> ~/workspace/ai-trading-agent
   cd ~/workspace/ai-trading-agent
   ```
4. Restore `.env` and any DB backups from step 2 onto the new host.
5. Start the stack on the new host **in dry-run mode**, even if the old
   host was live — see [`start-stop.md`](start-stop.md). Do not start it
   in live mode yet.
6. Verify on the new host:
   - `/status` reflects correct account state (it will be querying the
     same Kraken account as the old host — this is expected and fine as
     long as the old host isn't *also* live at the same time; see step 8).
   - Heartbeat is being emitted and received.
   - A day or more of dry-run operation looks sane (no unexpected errors
     in logs) before proceeding — don't rush this step just because the
     old host is sitting idle.
7. Once confident in the new host, prepare for cutover:
   - Confirm the old host still has no open positions (or, if it does,
     plan the exact cutover moment around a moment when it's flat — do
     not run two hosts live against the same account simultaneously,
     even briefly).
8. Cutover:
   - Stop the stack on the **old host** entirely (`docker compose down`,
     per [`start-stop.md`](start-stop.md)).
   - Switch the **new host** to live mode (`TRADING_MODE=live` in its
     `.env`), restart it there.
   - Verify via `/status` that the new host is now the one actively
     managing the account, and re-enable trading (`/resume kill_switch`)
     from the new host only.
9. Rotate the Kraken API key's IP whitelist to the new host's IP (see
   [`key-rotation.md`](key-rotation.md) — this is effectively a forced
   rotation as part of migration, since the IP whitelist changes).
10. Monitor closely for the first day after cutover — this is the one
    point in this runbook where slightly closer-than-usual attention is
    warranted, even though the system remains safe-by-default throughout.
11. Once stable, decommission the old host's copy: revoke any credentials
    that were only ever meant for it (if separately scoped — otherwise
    covered by step 9), and securely wipe `.env` / any local secrets left
    on it.

## Rollback

If the new host shows problems after cutover (step 8) and you need to
revert:

1. Engage [kill switch](kill-switch.md) or, if positions are open and you
   distrust the new host's state, [nuclear protocol](nuclear-protocol.md).
2. Stop the stack on the new host.
3. Re-verify the old host still has correct `.env`/config (it wasn't
   deleted, just stopped, in step 8).
4. Restart the old host per [`start-stop.md`](start-stop.md), re-verify
   `/status`, and resume from there while you diagnose the new host's
   issue at leisure.

## TBD

- Mini-PC provisioning checklist specifics — TBD (Phase 4).
- Ledger DB backup/restore mechanism — TBD (Phase 3), needed before this
  runbook's step 2/4 can be fully concrete.
