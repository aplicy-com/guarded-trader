# Runbook — Kill switch

**What this does:** blocks all **new** order entry. Existing open
positions are left running with their own stop-losses/take-profits intact
— this is *not* the same as flattening. If you need existing positions
closed too, use [`nuclear-protocol.md`](nuclear-protocol.md) instead, or
in addition.

**When to use:** you want trading to stop starting new positions right
now, and you're not (yet) sure the system's view of the world is wrong —
if you *do* think data or connectivity is untrustworthy, go straight to
the nuclear protocol instead.

## Engaging the kill switch

1. Open Telegram, go to the bot chat.
2. Send: `/kill`
3. Expect a reply within the same monitoring cycle (a few seconds to a
   couple of minutes) confirming: kill switch engaged, timestamp, current
   open positions (if any).
   - If you get **no reply** within a few minutes: the Telegram control
     path itself may be down. Go to the host directly (see step 4).
4. If Telegram isn't responding, connect to the host (SSH via Tailscale,
   or directly if you're at the machine) and stop new entries at the
   source:
   ```
   docker compose --env-file .env -f infra/docker-compose.yml exec conductor \
     python -m conductor.cli kill --operator <your name>
   ```
   Expected output: `halt #<n> engaged` then `primary: pause_entries: ok`.
   If a line says `FAILED`, the halt is still recorded and Conductor
   re-applies it every minute; check again with
   `python -m conductor.cli halts`. (**Until Telegram lands in 3A-4 this CLI
   is the primary way, not just the fallback.**)

   If Conductor itself cannot be reached and you need to act now, stopping
   the `freqtrade` container directly prevents any new order placement:
   ```
   docker compose -f infra/docker-compose.yml stop freqtrade
   ```
   This is a blunter tool than the kill switch — it also stops management
   of existing positions' exits, so only use it if you can't reach
   Conductor and need to act now. Follow up with proper diagnosis once
   you're able to.
5. Verify the kill switch actually engaged:
   - Telegram: `/status` — should show halt type `kill_switch`, active.
   - CLI: `python -m conductor.cli halts` lists active halts, e.g.
     `#1 kill_switch [all instances] ACTIVE :: kill switch engaged by ...`.
6. **You do not need to do anything else right now.** New entries are
   blocked. Existing positions (if any) continue to be managed by
   Freqtrade's own stop-losses. There is no time pressure to diagnose the
   underlying cause at 2am — go back to sleep if that's what brought you
   here; review in the morning.

## Understanding why it engaged (if it engaged automatically)

Before clearing the halt, look at *why* it fired — clearing it blind risks
walking straight back into the same condition.

1. Telegram: `/status` — shows halt reason (which of daily loss limit,
   max drawdown, consecutive-loss breaker, or manual command triggered
   it — see R4 in `docs/02-requirements.md`).
2. If it was a manual `/kill` you or someone else sent: no further
   investigation needed, skip to "Re-enabling" when ready.
3. If it was automatic:
   - **Daily loss limit** — check today's realized/unrealized P&L via
     `/status`. Expected to happen occasionally; if the loss looks
     consistent with normal strategy variance, this is the system working
     as designed.
   - **Max drawdown** — check equity vs. peak via `/status`. This is a
     more serious trigger; consider whether the current live strategy
     needs to be demoted back to paper pending research-loop review,
     rather than immediately re-enabled.
   - **Consecutive-loss breaker** — check which strategy/pair via
     `/status`. Consider whether that specific strategy should be paused
     pending review even after the global halt is cleared.
   - If you don't understand why it fired, **do not re-enable** — leave it
     halted and investigate further when you're able to (this is safe;
     see step 6 above).

## Re-enabling

1. Only after you understand why it fired (or confirmed it was a
   deliberate manual kill).
2. Telegram: `/resume kill_switch`. CLI (current):
   `python -m conductor.cli clear-halt <id> --operator <your name> --note "why"`
   (the id comes from `python -m conductor.cli halts`). It records you as
   the operator, then tells Freqtrade to resume; if it prints `FAILED`,
   Freqtrade stays paused (safe): fix the cause and run the same command
   again. If the original breach is still true the halt comes back within a
   minute: that is the system working, not a bug.
3. Expect a confirmation reply with your identity and timestamp logged.
4. Verify: `/status` — halt should show cleared, mode active.
5. If the halt reason suggested a specific strategy or pair should stay
   paused even though the global kill switch is cleared — TBD (Phase 3):
   per-strategy pause is not yet a separate control from the global kill
   switch. For now, treat any doubt about a specific strategy as a reason
   to leave the global kill switch engaged until the research loop or a
   human review addresses it.

## Common mistakes to avoid

- Re-enabling immediately without checking the reason "because the alert
  woke me up and I want it to stop" — the alert is not urgent, but
  re-enabling blind can be.
- Confusing this with the nuclear protocol — kill switch does **not**
  touch existing open positions.
