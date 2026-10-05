# Runbook — Nuclear protocol

**What this does:** cancels open orders, flattens (closes) open positions
where it is safely possible to do so, and halts all new entry. This is
the "we no longer trust what we think is true" button — use it for data
loss, exchange outage/anomaly, or any situation where the system's
recorded state might not match reality.

**When to use:** any of —
- You suspect the exchange connection or data feed is unreliable
  (stale prices, missing fills, contradictory balances).
- Kraken itself is reporting an outage or you can't reach its status page
  / API.
- The system's reported state (positions, balance) doesn't match what you
  see on Kraken's own website/app.
- Anything else that makes you generally distrust the current state.
- You've been asked to do this by a more specific incident procedure that
  points here.

If you're not sure whether this or the plain [kill switch](kill-switch.md)
is the right tool: **use this one.** It does everything the kill switch
does, plus flattening — the extra step (closing positions) is reversible
in the sense that you can always re-enter later; leaving a bad position
open while you're unsure of the system's state is not something you can
take back.

## Steps

1. **Do not panic-close your laptop or walk away yet** — the next few
   steps take under two minutes and matter more than anything else you
   could be doing right now.
2. Open Telegram, go to the bot chat.
3. Send: `/flatten`, then answer the bot's prompt with `yes <code>` (the
   4-character code it shows) within 60 s. This closes every open position
   at market, so the confirmation is deliberate: a wrong code or a late
   answer does nothing, send `/flatten` again.
4. Expect a reply `Nuclear #<n>: all steps ok` listing each step, each
   prefixed with the instance name (`primary: pause_entries: ok`, then
   `cancel_order:<id>` only if an order was open, `force_exit_all` only if a
   position was open, `confirm_flat`, `stop`), and a matching `NUCLEAR #<n>`
   alert. It can take up to ~30 s after the `yes` for the reply to arrive. If a step says `FAILED`, the
   halt is still recorded and entries stay blocked; see step 9.
   - **If you get no reply within a couple of minutes**, Telegram control
     may be down along with whatever else is wrong. Go to step 8
     (manual/host-level fallback) now — do not keep retrying Telegram.
5. Once confirmed, verify independently on Kraken's own web/app interface
   (not just the bot's word for it). *In dry-run (Phase 3) nothing exists on
   Kraken: skip this and use `scripts/drill-check.sh` on the VPS instead,
   which reads Freqtrade's own view.*
   - Open Orders — should show none remaining (or only ones you
     understand and expect, e.g. one caught mid-cancel — re-check in a
     minute).
   - Positions/Balances — should show flat (all crypto positions closed)
     unless the confirmation message explicitly told you a specific
     position could **not** be flattened (e.g. exchange rejected the
     close order) — in that case, go to step 9.
6. Log what happened somewhere you'll remember (a note, a message to
   yourself) — what you observed, what time, what you did. This isn't
   optional bookkeeping-for-its-own-sake: it's what lets you (or a future
   ADR/runbook update) figure out if this runbook needs to change.
7. **You do not need to fix the underlying cause right now.** The system
   is halted and flat (or as flat as it could get). Go back to sleep if
   that's why you're reading this. Full incident review can happen in the
   morning. To resume later, see "Re-enabling" in `kill-switch.md`
   (`/resume <halt id>`, or `clear-halt` on the CLI).
8. **Fallback if Telegram is unreachable but the host is:** run the same
   action as `/flatten` from the host's shell (`make ssh`, then
   `cd /opt/ai-trading-agent`):
   ```
   docker exec ai-trading-agent-conductor \
     python -m conductor.cli nuclear --operator <your name> --confirm-flatten-everything
   ```
   Expected output: `halt #<n> engaged`, then per step `ok` lines in this
   order: `pause_entries`, `cancel_order:<id>` (only if any), `force_exit_all`,
   `confirm_flat`, `stop`. If `confirm_flat` says `FAILED`, positions were
   not all closed within 30 s: the bot is left **paused, not stopped**, so it
   keeps managing its exits; check Kraken and go to step 9 if needed.

   **Fallback if Conductor itself is unreachable:**
   - Connect to the host (`make ssh`, or directly).
   - Stop Freqtrade to guarantee no further automated activity:
     ```
     docker stop ai-trading-agent-freqtrade
     ```
     (Plain `docker stop`: `docker compose` needs `.env` to parse the file.)
   - Log into Kraken directly (web or app) and manually cancel any open
     orders and close any open positions.
   - This is slower and more manual than the automated path, but it works
     even if the whole trading-stack host is compromised or unreachable —
     Kraken's own interface doesn't depend on any of our infrastructure.
   - Once flat, continue from step 6.
9. **If a position could not be flattened automatically** (exchange
   rejected the order, e.g. below minimum size, or market is halted):
   - Try once via Kraken's own interface directly.
   - If it still won't close, this is now a "monitor and wait" situation
     rather than a "fix it at 2am" situation — the position is small ($100
     principal scale) and bounded. Note it, set a reminder to check again
     in a few hours, and do not take further automated or manual action
     that could make things worse (e.g. don't try increasingly aggressive
     order types at 2am while half-asleep).

## After the fact (when you're properly awake)

1. Review what triggered the need for this — was it a real exchange
   issue, a bug, or a false alarm?
2. Check the ledger for the full sequence of events with timestamps.
3. Decide whether re-enabling is appropriate, and whether any strategy
   should be demoted back to paper first (see
   [`kill-switch.md`](kill-switch.md) re-enabling section — nuclear
   protocol re-enables the same way: `/resume <halt id>`, with the id from
   `/halts`; it also starts the stopped bot again).
4. If this exposed a real gap (e.g. Telegram was down when you needed it,
   a position wouldn't flatten), that's a risk-register/runbook update to
   make once you're rested — not a 2am task.

## Common mistakes to avoid

- Trying to be clever and closing positions manually on Kraken's site
  *and* via `/flatten` at the same time — this can race and produce
  confusing duplicate-cancel errors. Try the automated path first (step
  3), only fall back to manual (step 8) if it doesn't respond.
- Treating "the position wouldn't flatten" as an emergency requiring
  aggressive retries at 2am — it's small money and bounded; wait and
  retry when awake.
