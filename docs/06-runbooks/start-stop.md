# Runbook — Start / Stop the trading stack

**When to use:** starting the stack for the first time each day/session,
restarting after a config change, or shutting down deliberately (e.g.
before travel, before a host update).

**Before you start:** know which mode you intend — `dry_run` (paper) or
`live`. If you are not 100% sure which one you mean, treat it as
`dry_run` and check `TRADING_MODE` in `.env` before proceeding.

## Starting the stack

1. Open a terminal on the trading host.
2. `cd` into the project directory (`~/workspace/ai-trading-agent`, or
   wherever it's checked out on this host).
3. Confirm you are on `main` and up to date:
   ```
   git status
   git pull
   ```
   If `git status` shows anything unexpected (uncommitted changes you
   didn't make, a branch you don't recognize), **stop** — do not proceed.
   Something else may have touched this host. Investigate first.
4. Confirm `.env` exists and `TRADING_MODE` is set to the value you
   intend:
   ```
   grep TRADING_MODE .env
   ```
   If it says `live` and you meant to start in paper mode (or vice versa),
   fix it now before continuing. Starting `live` by accident is the single
   most avoidable mistake this runbook exists to prevent.
5. Confirm the host will not sleep while the stack runs. Amphetamine is
   the sleep-disable mechanism (not `pmset`, not `caffeinate`): a
   dedicated, always-on macOS login session with Amphetamine configured
   to keep the Mac awake with the lid closed — see
   [`../../infra/README.md`](../../infra/README.md#sleep-disable-mac-host)
   for the full setup.
6. Start the stack:
   ```
   docker compose -f infra/docker-compose.yml up -d
   ```
7. Check that both services are running:
   ```
   docker compose -f infra/docker-compose.yml ps
   ```
   You should see `conductor` and `freqtrade` both `Up`. If either is not,
   go to step 8 (do not proceed to step 9 with a service down).
8. If a service failed to start:
   - Check its logs: `docker compose logs <service-name> --tail 100`.
   - Do not retry blindly more than once — if it fails a second time,
     stop and investigate the log output before trying again.
9. Confirm Conductor reports healthy and **not halted**:
   - Telegram: send `/status`.
   - Expect: current mode (`dry_run`/`live`), no active halt, last
     heartbeat time recent.
   - If `/status` shows an active halt you did not expect, **do not
     assume it's stale** — go to
     [`kill-switch.md`](kill-switch.md) to understand why before clearing
     it.
10. You're done. The stack runs unattended from here; Telegram will alert
    you on any halt or error.

## Stopping the stack

1. Decide: do you need positions flattened first, or is a clean stop with
   open positions left in place acceptable? (Open positions left running
   unmonitored while the stack is down is **not** acceptable — Freqtrade
   is what manages their stop-losses. If you are stopping for more than a
   few minutes and have open positions, flatten first.)
2. If you need to flatten first: follow
   [`kill-switch.md`](kill-switch.md) (engage kill switch, confirm no new
   entries) and, if positions are open, the flatten step in
   [`nuclear-protocol.md`](nuclear-protocol.md) before continuing.
3. Confirm no open positions (or that you've deliberately decided to leave
   them, per step 1):
   - Telegram: `/status`.
4. Stop the stack:
   ```
   docker compose -f infra/docker-compose.yml down
   ```
5. Confirm both containers are stopped:
   ```
   docker compose -f infra/docker-compose.yml ps
   ```
   Expect no running containers listed.
6. If this was a deliberate extended pause (e.g. before travel), note it
   somewhere you'll see it — there is currently no automated "planned
   absence" mode (risk register O6, TBD Phase 4).

## If something looks wrong at any step

Do not push through. Stop, and if positions are open and you're unsure of
system state, go straight to [`nuclear-protocol.md`](nuclear-protocol.md)
rather than continuing this runbook.
