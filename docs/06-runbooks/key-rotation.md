# Runbook — Key rotation

**What this covers:** rotating the Kraken API key, the Telegram bot token,
and the Anthropic API key. Do this on a regular cadence (TBD Phase 2 —
suggest every 90 days as a starting default) and immediately any time you
suspect a leak (risk register S1).

**General principle for all three:** create the new credential, verify it
works, switch the running system to it, **then** revoke the old one —
never revoke first. A gap with no valid credential is worse than a brief
overlap with two valid ones.

## Kraken API key rotation

1. Log into Kraken directly (not via any automation).
2. Create a **new** API key with exactly these permissions (see
   `docs/04-architecture/security.md`):
   - Query Funds: on
   - Query Open/Closed Orders: on
   - Query Ledger Entries: on
   - Create/Modify/Cancel Orders: on
   - **Withdraw Funds: off** — double-check this specifically, it's the
     one that matters most.
   - IP whitelist: set to the trading host's current IP.
3. Before doing anything else, re-read the permissions you just set on
   the new key back on Kraken's own confirmation screen. Confirm
   withdrawal is off. This step exists because it's the easiest thing to
   get wrong while tired.
4. Engage the [kill switch](kill-switch.md) (`/kill` via Telegram) before
   swapping credentials, so no order is in flight mid-swap.
5. Update `.env` on the host with the new `KRAKEN_API_KEY` /
   `KRAKEN_API_SECRET`. Do **not** commit this file (it's git-ignored;
   double check with `git status` that it doesn't show up as a tracked
   change).
6. Restart the stack per [`start-stop.md`](start-stop.md) so it picks up
   the new credentials.
7. Verify the new key works:
   - `/status` via Telegram should show balances/positions correctly
     (proves the query permission works).
   - If in dry-run, no live order test needed. If about to go live, verify
     with a small test in dry-run mode first, then confirm live mode
     separately once you're ready — don't test live orders as part of a
     routine rotation.
8. Once confirmed working, go back to Kraken and revoke the **old** key.
9. Re-enable trading: `/resume kill_switch` (see
   [`kill-switch.md`](kill-switch.md)).
10. Update your rotation-tracking note (last rotated date) — TBD (Phase 2)
    where this is tracked; until then, a personal note is fine.

## Telegram bot token rotation

1. In Telegram, talk to @BotFather, select the bot, regenerate its token.
2. Update `TELEGRAM_BOT_TOKEN` in `.env` on the host.
3. Restart the stack per [`start-stop.md`](start-stop.md).
4. Send `/status` from your existing chat to confirm the bot still
   responds under the new token (the chat ID allowlist doesn't change,
   only the token authenticating the bot itself).
5. If you also suspect your chat/allowlist may be compromised, review
   `TELEGRAM_ALLOWED_CHAT_IDS` in `.env` at the same time and remove
   anything you don't recognize.

## Anthropic API key rotation

1. Generate a new key in the Anthropic console.
2. Update `ANTHROPIC_API_KEY` in `.env` on the host.
3. Restart the Conductor service (the research loop only needs this key
   for its nightly run — no need to touch Freqtrade or engage the kill
   switch for this one, since the LLM never touches the order path,
   [`ADR-0003`](../05-adr/0003-llm-never-orders.md)).
4. Verify on the next scheduled research-loop run (or trigger one
   manually if that control exists — TBD Phase 3) that it completes
   without an auth error.
5. Revoke the old key once confirmed.

## If you suspect an actual leak (not routine rotation)

1. Rotate the affected credential **immediately**, following the relevant
   section above, out of its normal cadence.
2. For the Kraken key specifically: also check Kraken's account activity
   log for anything you don't recognize (orders, withdrawal attempts —
   there shouldn't be any withdrawal capability to begin with, but check
   for attempted withdrawal API calls that would have been rejected).
3. If you find anything unexpected on Kraken (even a rejected withdrawal
   attempt), treat this as a security incident: engage
   [nuclear protocol](nuclear-protocol.md), rotate all three credentials,
   and don't resume trading until you understand how the leak happened.

## TBD

- Formal rotation-cadence tracking mechanism — TBD (Phase 2).
- Manual research-loop trigger for step 4 of the Anthropic rotation — TBD
  (Phase 3).
