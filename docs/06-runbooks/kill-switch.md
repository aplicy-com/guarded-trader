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
3. The bot replies with a confirmation prompt containing a 4-character
   code, e.g. `Reply \`yes K7QX\` within 60 s`. Send exactly that: `yes K7QX`.
   (If you wait longer than 60 s or mistype the code, nothing happens, and
   the bot says `Confirmation expired` or `Wrong code`: just send `/kill`
   again.) You then get a reply such as
   `Kill switch #3: all steps ok` followed by `primary: pause_entries: ok`,
   and an alert `HALT #3 [kill_switch] ...`.
   - If you get **no reply** within a few minutes: the Telegram control
     path itself may be down. Go to the host directly (see step 4).
4. If Telegram isn't responding, connect to the host (`make ssh` from the
   Mac, then `cd /opt/ai-trading-agent`) and stop new entries at the
   source:
   ```
   docker exec ai-trading-agent-conductor python -m conductor.cli kill --operator <your name>
   ```
   Expected output: `halt #<n> engaged` then `primary: pause_entries: ok`.
   If a line says `FAILED`, the halt is still recorded and Conductor
   re-applies it every minute; check again with
   `python -m conductor.cli halts`. (This CLI is the fallback for when
   Telegram is unreachable; it does exactly what `/kill` does.)

   If Conductor itself cannot be reached and you need to act now, stopping
   the `freqtrade` container directly prevents any new order placement:
   ```
   docker stop ai-trading-agent-freqtrade
   ```
   (Plain `docker stop`, not `docker compose`: compose needs the `.env`
   variables to even parse the file and can fail when you least want it to.
   The container stays stopped until you run
   `docker start ai-trading-agent-freqtrade`; `restart: unless-stopped` does
   not bring back a container you stopped by hand.)
   This is a blunter tool than the kill switch — it also stops management
   of existing positions' exits, so only use it if you can't reach
   Conductor and need to act now. Follow up with proper diagnosis once
   you're able to.
5. Verify the kill switch actually engaged:
   - Telegram: `/status` — should show `HALTED (1):` with `#<id> kill_switch`
     and `Freqtrade primary: paused`.
   - On the VPS: `scripts/drill-check.sh --expect-state paused --expect-halts 1`
     prints `CHECK PASS`.
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
2. Telegram: `/halts` to see the halt id, then `/resume <id>` and answer
   `yes <code>` as above. CLI alternative:
   `python -m conductor.cli clear-halt <id> --operator <your name> --note "why"`
   (the id comes from `python -m conductor.cli halts`). It records you as
   the operator, then tells Freqtrade to resume; if it prints `FAILED`,
   Freqtrade stays paused (safe): fix the cause and run the same command
   again. If the original breach is still true the halt comes back within a
   minute: that is the system working, not a bug.
3. Expect a reply `Cleared halt #<id>.` and `primary: resume: ok`. Your
   identity and the time are logged in the audit log.
4. Verify: `/status` — `Halts: none` and `Freqtrade primary: running`
   (or `scripts/drill-check.sh --expect-state running --expect-halts 0`).
5. If the halt reason suggested a specific strategy or pair should stay
   paused even though the global kill switch is cleared — TBD (Phase 3):
   per-strategy pause is not yet a separate control from the global kill
   switch. For now, treat any doubt about a specific strategy as a reason
   to leave the global kill switch engaged until the research loop or a
   human review addresses it.

## If Freqtrade restarts while a halt is active

Freqtrade boots `paused` (`initial_state: paused`, [`ADR-0018`](../05-adr/0018-fail-closed-freqtrade-boot.md)): it
manages exits of open positions but cannot open a new one. Conductor is the only thing that starts it, and only when no
halt is active. So after a Freqtrade restart (a crash, a reboot, an unattended upgrade, a deploy) a halted system
stays paused, with no window in which it could trade. With no halt, Conductor starts it again within about a minute
and posts `BOOT primary: Freqtrade restarted paused; no halt active, started`. If Conductor is down, Freqtrade stays
paused after a restart: no new entries until Conductor is back (the heartbeat alert tells you). Drill 3
([`docs/drills/README.md`](../drills/README.md)) proves this.

## Common mistakes to avoid

- Re-enabling immediately without checking the reason "because the alert
  woke me up and I want it to stop" — the alert is not urgent, but
  re-enabling blind can be.
- Confusing this with the nuclear protocol — kill switch does **not**
  touch existing open positions.
