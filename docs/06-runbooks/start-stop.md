# Runbook — Start / Stop the trading stack

**When to use:** starting the stack for the first time each day/session,
restarting after a config change, or shutting down deliberately (e.g.
before travel, before a host update).

**On the VPS** (the normal host since 3A-0): `make ssh`, then `cd /opt/ai-trading-agent`.
Every `docker compose` command there needs `--env-file .env`, i.e.
`docker compose --env-file .env -f infra/docker-compose.yml ...` (the compose file
refuses to parse without the variables in `.env`). Where the steps below say
"Amphetamine" or `git pull`, they describe the old Mac host and do not apply:
the VPS is updated with `make deploy` from your Mac. After any start or restart
run `scripts/drill-check.sh`, which prints halt state, Freqtrade state, open
positions, data counts and the last heartbeat in one go. A restart of either
container is safe while a halt is active: the halt is stored in Conductor's
ledger and Freqtrade always boots `paused` (ADR-0018). With no halt, expect
Freqtrade to read `paused` for up to about a minute after a start, until
Conductor starts it (see [`kill-switch.md`](kill-switch.md), "If Freqtrade
restarts while a halt is active").

**Live pilot (ADR-0019):** once the server has been switched to live
(`scripts/trading-mode.sh live`, see [`go-live-pilot.md`](go-live-pilot.md)), the file
`.trading-mode` says `live` and every `docker compose ...` above must go through
`scripts/compose.sh ...` instead (it adds the live override: `scripts/compose.sh up -d`,
`scripts/compose.sh down`, `scripts/compose.sh ps`). A plain
`docker compose -f infra/docker-compose.yml up -d` would start the **dry-run** stack
over the live one (safe direction: it cannot place real orders, but it is not what you
meant). `make deploy` already uses the wrapper. To switch modes use only
`scripts/trading-mode.sh`; never edit `.trading-mode` by hand.

**Before you start:** know which mode you intend — `dry_run` (paper) or
`live`. If you are not 100% sure which one you mean, treat it as
`dry_run` and check `TRADING_MODE` in `.env` before proceeding.

## Starting the stack

1. Open a terminal on the trading host.
2. `cd` into the project directory (`<repo-dir>`, or
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
   - Expect: `Mode: dry_run` (or `live`), `Halts: none`,
     `Freqtrade primary: running`. (Heartbeat: the dashboard's Monitoring box,
     or `scripts/drill-check.sh`, shows it `ok` within about 5 minutes of a start.)
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

## R5 abort — Conductor refuses to start, or will not start Freqtrade, because of an unexplained balance

**What you see:** `STARTUP REFUSED: R5 account isolation violated: <pair>: unexplained <n> <ASSET>`
in `docker logs ai-trading-agent-conductor` and a Telegram alert `REFUSING TO START (R5)`; or,
with Conductor already running, a Telegram alert `BOOT primary: NOT started, stays paused: R5
account isolation: ...` (Freqtrade stays paused: it cannot open a position). Or
`scripts/trading-mode.sh live` stops at "R5 gate failed" and the server is `live-pending`.

**What it means (requirement R5, AC5.3):** a coin the system trades (a whitelisted pair's base
asset) is on the Kraken account in an amount the system did not buy and the ledger has not been
told to ignore. The system will not guess whether that is yours to keep or its to trade. **It
never clears itself, and restarting does not help.**

**Which tool to use:** on the VPS, in `/opt/ai-trading-agent`, every command below is
`scripts/trading-mode.sh cli <command>` (it runs the Conductor CLI against the **live** ledger,
and works whether or not the live Conductor is running).

1. See exactly what is unexplained:
   ```
   scripts/trading-mode.sh cli isolation-check
   ```
   Expected: a table with one row per whitelisted asset (BTC, XRP, SOL, LINK, LTC) and the line
   `R5 CHECK FAIL: unexplained <ASSET>`. The `unexplained` column is the amount in question.
2. Decide, for each unexplained asset, which of these is true. If you are not sure, do **A**.
   - **A. It is yours and you want to keep it** (an old purchase, a gift, a deposit):
     record it as excluded. This is a permanent, audited declaration made in your name:
     ```
     scripts/trading-mode.sh cli exclude-balance --asset LTC --operator <your name> --note "bought 2025, personal"
     ```
     Expected: `excluded <n> LTC (total now excluded for that asset)`. It refuses to exclude
     more than the account holds beyond the system's own positions. To exclude only part of the
     balance add `--amount <n>`.
   - **B. It should not be on this account** (a mistaken deposit): move it off Kraken by hand,
     on Kraken's own site (never by anything in this repo), wait for it to leave, then go to 3.
   - **C. The system bought it** but the ledger does not know (this should never happen): stop.
     Do not exclude it. Engage `/kill`, and treat it as an incident: record what you saw and ask
     for help; the ledger and Freqtrade disagree.
3. Prove it is clear:
   ```
   scripts/trading-mode.sh cli isolation-check
   ```
   Expected: `R5 CHECK PASS`.
4. Resume:
   - Conductor refused at startup: `scripts/compose.sh up -d conductor` (or re-run
     `scripts/trading-mode.sh live` if you were switching). Expected: the container stays `Up`.
   - Conductor was running and only withheld the Freqtrade start: nothing to do. It re-checks
     every minute, starts Freqtrade once the check passes, and sends `BOOT primary: ... started`.
5. Check: `scripts/drill-check.sh` shows `freqtrade: running` (or `paused` if a halt is active).

Never "fix" this by deleting rows from the ledger (the table refuses edits and deletes), by
adding the asset to the blacklist *and* ignoring the alert, or by editing the whitelist to hide
it: R5 exists so that none of those can quietly turn your own coins into the system's.
