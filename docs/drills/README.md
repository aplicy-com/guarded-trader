# 3A-6 drills — safety layer proof, run on the VPS in dry-run

**What this is:** the six drills the 3A exit gate requires
([`phase-3-plan.md`](../phase-3-plan.md) §3A-6). Each one proves a safety path
works on the real VPS, not just in unit tests. Nothing here touches Kraken: the
stack is in `dry_run`, so no real order, key or money is involved.

**Who runs what:** you run every command; paste the output back and it goes
into the results file ([`results-2026-10-04.md`](results-2026-10-04.md); a blank
copy of the format is [`TEMPLATE.md`](TEMPLATE.md)). Claude Code does not touch
the VPS.

**Rules:**
- If any "Expected" line does not match, **stop**, do the drill's *If it fails*
  section, and record it as `FAIL` with the real output. A failed drill that is
  recorded honestly is a good result; fixing the cause and re-running it is
  how the gate is met. Never edit an output to look right.
- Dry-run only. Before you start, `grep '^TRADING_MODE' .env` on the VPS must say
  `dry_run`. If it says anything else, stop.
- Drills write to the real ledger and audit log (halts and clears are
  append-only history). That is intended: it is the proof.

## Order to run them in

| # | Drill | Why here | Time |
|---|---|---|---|
| 0 | Setup and baseline | everything below needs it | 20 min |
| 1 | **Drill 2**: nuclear | **first, while a dry-run position is open** (Conductor cannot open one, by design, and the strategy may close it at any time). The drill closes it. | 15 min |
| 2 | **Drill 5**: record the backup/restore pass | already done; paste today's output | 5 min |
| 3 | **Drill 6**: VPS rebuild | **destroys and recreates the server, which restarts the 7-day soak clock** (3A exit gate: "VPS running ≥ 7 days"). Done before the remaining drills so the soak runs on the final server, and drills 1, 3 and 4 then also prove the *rebuilt* box works. | 1.5-2 h |
| 4 | **Drill 1**: kill switch | quick; also proves Telegram on the new box | 15 min |
| 5 | **Drill 3**: restart persistence | uses a halt; proves the fail-closed boot (ADR-0018) | 25 min |
| 6 | **Drill 4**: heartbeat silence | needs a 15-minute wait; do it last so nothing else is running during it | 30 min |

If you would rather run them 1 → 6 as the plan lists them, nothing breaks, but
then the rebuild (drill 6) resets the soak clock and drills 1-4 will have run
on the server you just threw away. Start the 7-day soak after the last drill
passes either way, with no halt active.

Drill 2 is the full version only while a position is open: if you reach it and
`positions=0`, use the no-position variant and record `PARTIAL`; the gate needs
a full run. This README does **not** use a manual force-entry: it needs a config
change on the trading path, which is your call, not part of a drill script.

## Setup (once per session)

**Merge and deploy first.** `make deploy` ships `main`, so this branch's files
(`scripts/drill-check.sh`, the fixed runbooks, `make deploy-files`) must be on
`main`:
```
git switch main && git merge --no-ff chore/3a-drills
make deploy
```
Expected: the rsync list includes `scripts/drill-check.sh`, then
`Container ai-trading-agent-conductor  Recreated` / `Started` (the code changed:
fail-closed boot, ADR-0018). The Freqtrade container is **not** recreated and
keeps running with its old config, because its config is a bind-mounted file. The
new `initial_state: paused` applies at its next restart, so do that now, once,
and watch it come back (this is also a free first look at drill 3):
```
make ssh
cd /opt/ai-trading-agent
export C="docker compose --env-file .env -f infra/docker-compose.yml"
$C restart freqtrade
scripts/drill-check.sh --watch 5
```
Expected: `freqtrade=unreachable(...)` for ~20-40 s, then `freqtrade=paused`, then
`freqtrade=running` within about a minute (Conductor started it: no halt is
active), and a Telegram alert `BOOT primary: Freqtrade restarted paused; no halt
active, started`. `freqtrade=running` must **never appear before** `paused`.
Ctrl-C. Check the open position is still listed (`positions=`): a paused boot
still manages its exits.

**On the VPS**, at the start of every drill session:
```
make ssh
cd /opt/ai-trading-agent
export C="docker compose --env-file .env -f infra/docker-compose.yml"
grep '^TRADING_MODE' .env
scripts/drill-check.sh
```
Expected: `TRADING_MODE=dry_run`, then the report: both containers `Up ... (healthy)`,
`halts (active)` = `no active halts`, `freqtrade state: running  dry_run: True` (it boots `paused` and Conductor starts it
within about a minute, so just after a restart `paused` is normal),
a `data` section with `principal=100 USD`, `heartbeat: ok ...`, and a last
`SUMMARY` line. (`C` is just a shorthand for the long compose command and only
lives in this shell. `scripts/drill-check.sh --help` lists its options.)

**Baseline** (write these down; "restored" in drill 6 is compared to them):
the whole `drill-check.sh` output, `docker exec ai-trading-agent-conductor python -m conductor.cli capital`,
and `terraform -chdir=infra/terraform output -raw ipv4` (on the Mac).

**Telegram** (from your phone, in the bot chat): send `/status`. Expected: a
reply starting `Mode: dry_run`. No reply means the bot or your chat ID is wrong:
fix that before any drill that uses Telegram (1 and 2).

**How to read `drill-check.sh`:**
| Command | Use |
|---|---|
| `scripts/drill-check.sh` | full report |
| `scripts/drill-check.sh --brief` | one `SUMMARY` line |
| `scripts/drill-check.sh --watch 5` | `SUMMARY` line every 5 s (Ctrl-C to stop); measures how long a state takes to change |
| `scripts/drill-check.sh --expect-state paused --expect-halts 1` | prints `CHECK PASS` or `MISMATCH`/`CHECK FAIL` (exit 1). Also `--expect-positions N` |

`freqtrade=` is `running`, `paused` (new entries blocked: what the kill switch
sets) or `stopped` (what nuclear sets). `unreachable(...)` means Freqtrade's API
did not answer.

---

## Drill 1 — Kill switch via Telegram

**Proves:** `/kill` + confirmation blocks new entries, the halt is recorded, and
`/resume <id>` undoes it.
Runbook: [`kill-switch.md`](../06-runbooks/kill-switch.md).

**Preconditions**
- `scripts/drill-check.sh --expect-state running --expect-halts 0` prints `CHECK PASS`.
- `/status` answers in Telegram. Note the number of open positions (`positions=`).

**Steps**
1. *Negative checks first (nothing should change).* In Telegram: send `/kill`; the
   bot asks `Reply yes <CODE> within 60 s`. Reply `yes ZZZZ` (a wrong code).
   Expected: `Wrong code. Nothing was done. Send the command again.` Then send
   `/kill` again, wait **70 seconds**, reply with the right code. Expected:
   `Confirmation expired (60 s). Nothing was done.`
   On the VPS: `scripts/drill-check.sh --expect-state running --expect-halts 0` → `CHECK PASS`
   (both attempts changed nothing).
2. Telegram: `/kill`. Expected: `KILL SWITCH: block all new entries` and
   `Reply yes <CODE> within 60 s to confirm`. Reply `yes <CODE>` (the real code).
   Expected replies: `Kill switch #<N>: all steps ok` with `primary: pause_entries: ok`,
   and an alert `HALT #<N> [kill_switch] kill switch engaged by telegram:<your chat id>`.
   Write down `<N>`.
3. VPS: `scripts/drill-check.sh --expect-state paused --expect-halts 1 --expect-positions <baseline>`.
   Expected: `CHECK PASS`; the halts section shows `#<N> kill_switch [all instances] ACTIVE`.
   (Open positions are untouched: the kill switch does not close anything.)
4. Telegram: `/status`. Expected: `HALTED (1):`, `#<N> kill_switch`, `Freqtrade primary: paused`.
5. Telegram: `/resume <N>`. Expected: `RESUME: clear halt #<N> [kill_switch] ...`; reply
   `yes <CODE>`. Expected: `Cleared halt #<N>.` and `primary: resume: ok`, plus the alert
   `HALT #<N> [kill_switch] cleared by telegram:<your chat id>`.
6. VPS: `scripts/drill-check.sh --expect-state running --expect-halts 0` → `CHECK PASS`.

**Pass criteria:** every "Expected" above matched; state went running → paused → running;
the halt and its clear are visible in `scripts/drill-check.sh` ("recent, incl. cleared") and
on the dashboard's *Halts & audit* page. **Record:** the outputs of steps 3 and 6, the Telegram
replies (copy the text), the time you sent `/kill` and the time `paused` showed.

**If it fails / rollback**
- No Telegram reply at all: record `FAIL (Telegram)`, then do the same on the host:
  `docker exec ai-trading-agent-conductor python -m conductor.cli kill --operator maduka`, and later
  `... clear-halt <N> --operator maduka --note drill`. Look at
  `docker logs ai-trading-agent-conductor --tail 50`.
- Left `paused` after `/resume` (a `FAILED` line): run
  `docker exec ai-trading-agent-conductor python -m conductor.cli clear-halt <N> --operator maduka --note drill-retry`
  (safe to repeat: for an already-cleared halt it just re-sends resume). Last resort:
  `$C restart freqtrade` (it boots `running`).
- A halt you did not intend is still active: `docker exec ai-trading-agent-conductor python -m conductor.cli halts`,
  then clear it as above. Then re-check with `scripts/drill-check.sh`.

---

## Drill 2 — Nuclear via Telegram (`/flatten`)

**Proves:** `/flatten` cancels open orders, closes every open position, stops the
bot, and the halt persists until a human clears it. Runbook:
[`nuclear-protocol.md`](../06-runbooks/nuclear-protocol.md).

**Preconditions**
- `scripts/drill-check.sh --expect-state running --expect-halts 0` → `CHECK PASS`.
- **Full drill:** `positions=` is **at least 1** (there is one open on the VPS as of 2026-10-05; positions
  can close on their own, so check right before you start). Write down each position (`#id pair stake`
  and whether it shows `[open order]`). **No position any more?** Run the *no-position variant*
  below (it still proves pause + stop + halt persistence) and record the result as
  `PARTIAL (no position)`; the gate needs a full run later.
- It is dry-run: there is nothing to check on Kraken. Do not log into Kraken for this drill.

**Steps**
1. Telegram: `/flatten`. Expected: `FLATTEN: cancel open orders, market-close ALL positions, stop the bot`
   and the `yes <CODE>` prompt. Reply `yes <CODE>` within 60 s.
2. Wait up to about 35 seconds. Expected reply: `Nuclear #<N>: all steps ok` listing, in order:
   `primary: pause_entries: ok`; `primary: cancel_order:<id>: ok` (only if a position had an
   open order); `primary: force_exit_all: ok`; `primary: confirm_flat: ok`; `primary: stop: ok`.
   Plus alerts `HALT #<N> [nuclear] ...` and `NUCLEAR #<N>: all steps ok ...`.
3. VPS: `scripts/drill-check.sh --expect-state stopped --expect-halts 1 --expect-positions 0`.
   Expected: `CHECK PASS`, `freqtrade state: stopped`, `open positions: 0`, and the halts section shows
   `#<N> nuclear [all instances] ACTIVE`.
4. Telegram: `/trades`. Expected: your position(s) listed as closed with exit reason
   `force_exit` (it can take up to ~1 minute for the ledger to ingest them).
5. **Halt persisted:** `docker exec ai-trading-agent-conductor python -m conductor.cli halts`
   shows the nuclear halt `ACTIVE`; Telegram `/status` shows `HALTED (1)` and
   `Freqtrade primary: stopped`.
6. Telegram: `/resume <N>`, reply `yes <CODE>`. Expected: `Cleared halt #<N>.` and
   `primary: resume: ok` (this starts the stopped bot).
7. VPS: `scripts/drill-check.sh --expect-state running --expect-halts 0` → `CHECK PASS`.

**No-position variant:** same steps, but the reply in step 2 has only `pause_entries`,
`confirm_flat`, `stop` (no `force_exit_all`, because there is nothing to close), and step 4 is skipped.

**Pass criteria:** every "Expected" matched; positions went N → 0; state running → stopped → running;
the halt was `ACTIVE` until you cleared it. **Record:** outputs of steps 3, 5, 7, the Telegram
reply text, the positions before, the seconds from `yes` to the reply.

**If it fails / rollback**
- `confirm_flat` says `FAILED` (not flat in 30 s): the bot is left **paused, not stopped**, by design.
  Check `scripts/drill-check.sh`; send `/flatten` again (it re-runs the steps under the same halt).
  In dry-run the worst case is a leftover position: record it and continue to `/resume`.
- `force_exit_all` or `cancel_order` says `FAILED`: record the exact text and
  `docker logs ai-trading-agent-freqtrade --tail 80`. Do not retry blindly more than once.
- Stuck `stopped` after `/resume`: `docker exec ai-trading-agent-conductor python -m conductor.cli clear-halt <N> --operator maduka --note drill-retry`;
  last resort `$C restart freqtrade`.

---

## Drill 3 — Restart persistence and fail-closed boot

**Proves:** a halt survives a restart of Conductor, of Freqtrade and of both; **Freqtrade can never trade between
its own boot and Conductor's decision** (it boots `paused`, [`ADR-0018`](../05-adr/0018-fail-closed-freqtrade-boot.md));
Conductor starts it again only when no halt is active.
**Read this first:** with `initial_state: paused` a restarted Freqtrade is `paused` from its first moment. Under an
active halt it stays `paused`. With no halt, Conductor sends `start` on its next risk cycle (≤ 60 s) and posts
`BOOT primary: Freqtrade restarted paused; no halt active, started`. So in every `--watch` line of this drill,
**`freqtrade=running` while a halt is active is a FAIL**, however briefly.

**Preconditions:** `scripts/drill-check.sh --expect-state running --expect-halts 0` → `CHECK PASS`
(if you have just restarted Freqtrade, wait for it to read `running` first).

**Steps**
1. Engage the kill switch from the host (so this drill does not depend on Telegram):
   ```
   docker exec ai-trading-agent-conductor python -m conductor.cli kill --operator maduka
   ```
   Expected: `halt #<N> engaged` and `primary: pause_entries: ok`. Then
   `scripts/drill-check.sh --expect-state paused --expect-halts 1` → `CHECK PASS`.
2. **Restart Conductor only:**
   ```
   $C restart conductor
   sleep 45
   scripts/drill-check.sh --expect-state paused --expect-halts 1
   ```
   Expected: `CHECK PASS`. (Freqtrade was not restarted, so it stays paused; the halt came back from the
   ledger volume. `heartbeat:` reads `none sent since start` until the first ping, up to 5 minutes: normal.)
3. **Restart Freqtrade only, under the halt**, and watch:
   ```
   $C restart freqtrade
   scripts/drill-check.sh --watch 2
   ```
   Expected sequence in the `SUMMARY` lines: `freqtrade=unreachable(...)` for ~20-40 s, then `freqtrade=paused`, and it
   **stays `paused`**. Watch at least 90 seconds after the first `paused` line (longer than one risk cycle), then
   Ctrl-C. Pass: **no line shows `freqtrade=running`**. Keep the whole output.
   Then `scripts/drill-check.sh --expect-state paused --expect-halts 1` → `CHECK PASS`.
4. **Restart both, under the halt:**
   ```
   $C restart
   scripts/drill-check.sh --watch 2
   ```
   Expected: the same shape as step 3 (never `running`), and no `BOOT` alert in Telegram. Ctrl-C after 90 s of
   `paused`. Then `scripts/drill-check.sh --expect-state paused --expect-halts 1` → `CHECK PASS`, and `docker ps`
   shows both containers `healthy`.
5. *(Optional, more realistic: do it only if you can reach the Hetzner web console as a fallback.)*
   Reboot the host: `sudo reboot`. Wait ~3 minutes, `make ssh` again (it needs Tailscale to come back on its own),
   `cd /opt/ai-trading-agent`, `scripts/drill-check.sh --watch 2`. Expected: both containers back up by themselves
   (`restart: unless-stopped`) and the state is `paused` the whole time, never `running`.
6. **Clear the halt:** `docker exec ai-trading-agent-conductor python -m conductor.cli clear-halt <N> --operator maduka --note "drill 3"`.
   Expected: `cleared halt #<N>` and `primary: resume: ok`.
   `scripts/drill-check.sh --expect-state running --expect-halts 0` → `CHECK PASS`.
7. **The other half: restart with NO halt.** Now that nothing is halted:
   ```
   $C restart freqtrade
   scripts/drill-check.sh --watch 2
   ```
   Expected: `unreachable(...)`, then `freqtrade=paused`, then `freqtrade=running` within about 60-90 s of it
   becoming reachable, and a Telegram alert `BOOT primary: Freqtrade restarted paused; no halt active, started`.
   Write down the seconds spent `paused`. Ctrl-C once `running` is stable. If you have an open position, it must still
   be listed (`positions=`) the whole time.
8. *(Optional)* **Conductor down ⇒ stays paused.** `$C stop conductor`, then `$C restart freqtrade`, and
   `docker exec ai-trading-agent-freqtrade ...` is not needed: use `scripts/drill-check.sh --brief` a few times over
   two minutes. Expected: `freqtrade=paused` and it stays so (no entries, exits still managed). Then
   `$C start conductor`; within ~2 minutes it reads `running` and the `BOOT` alert arrives.

**Pass criteria:** the halt is `ACTIVE` after every restart; in steps 2-5 Freqtrade is **never** `running` while the
halt is active; step 6 clears cleanly; step 7 starts the bot by itself and alerts; positions survive restarts.
**Record:** the `--watch` output of steps 3, 4 and 7 (this is the evidence), the checks of steps 2 and 6, and
the seconds from "reachable" to `running` in step 7.

**If it fails / rollback**
- **`freqtrade=running` at any point while a halt is active:** record `FAIL` and keep the output. Engage again:
  `docker exec ... kill --operator maduka` (it reports `was already active` and re-applies the pause). Check
  `grep initial_state /opt/ai-trading-agent/services/freqtrade/user_data/config.dry_run.json` says `paused`
  and that Freqtrade was restarted after the deploy (a bind-mounted config is read at start only).
- The halt is gone after a restart: **serious** (halt state not persisted). Record `FAIL`, do not clear anything,
  run `... conductor.cli halts --all`, keep the output, and stop the drills until it is understood.
- Step 7 never goes `running` (stays `paused` with no halt): `docker logs ai-trading-agent-conductor --tail 80 | grep -i boot`
  (`boot_start_deferred`, `boot_start_failed`). It retries every cycle; if it will not start, clear by hand:
  `docker exec ... clear-halt <any cleared id> --operator maduka --note retry` re-sends `start`, or `$C restart freqtrade`
  then `/resume`. Record `FAIL`.
- A container will not come back: `$C up -d`, then `docker logs <name> --tail 80`.
- Always finish with the halt cleared and Freqtrade `running` (steps 6-7) so nothing is left halted.

---

## Drill 4 — Heartbeat silence (healthchecks.io)

**Proves:** if Conductor stops, healthchecks.io alerts you through a channel that does not depend on the VPS, within the
grace time, and tells you when it recovers. (Check settings: period 5 min + grace 10 min, so the alert is due
**15 minutes after the last ping**.)

**Preconditions**
- In healthchecks.io, the check for this system shows **up**, with a last ping under 5 minutes old.
- Its *Integrations* list your alert channels (email, and healthchecks.io's own Telegram integration). Use each
  channel's *Test* button once and confirm the test arrives on your phone. (This is separate from Conductor's Telegram bot.)
- `scripts/drill-check.sh --brief` shows `heartbeat="ok ..."`. No halt active.
- Phone notifications on, and be ready to note the time each alert arrives.

**Steps**
1. Write down **T0 = the check's last-ping time** (healthchecks.io page, in UTC) and the time now.
2. Stop Conductor:
   ```
   $C stop conductor
   docker ps -a --filter name=ai-trading-agent --format '{{.Names}}  {{.Status}}'
   ```
   Expected: conductor `Exited (0) ...`, freqtrade `Up ... (healthy)`. Write down **T_stop**. (Optional: Telegram
   `/status` now gets no reply, which shows the bot died with Conductor.)
3. Wait. healthchecks.io shows the check **late** after T0 + 5 min and **down** after T0 + 15 min. Expected: an alert on every
   channel by **T0 + 15 min** (allow up to 2 minutes for delivery). Write down, per channel and device, when it arrived and
   what it said.
4. Confirm it stayed down on its own: `docker ps -a --filter name=ai-trading-agent-conductor --format '{{.Status}}'`
   still `Exited` (a stopped container is not auto-restarted).
5. Recover: `$C start conductor`. Write down **T_start**. Within about 5-6 minutes (the first heartbeat is one interval after start)
   healthchecks.io returns to **up**, and a recovery notification arrives. Then
   `scripts/drill-check.sh --expect-state running --expect-halts 0`; the full report's `heartbeat:` says `ok`.

*(Optional, between steps 4 and 5, only if no halt is active and you accept a short entry pause)* restart Freqtrade
while Conductor is stopped: `docker restart ai-trading-agent-freqtrade`. Expected: it comes back `paused` and stays
`paused` (Conductor is the only thing that starts it). After step 5 it reads `running` again within ~2 minutes.

**Pass criteria:** an alert reached your phone on at least your primary channel no later than 17 minutes after T0; it named the check;
a recovery notice arrived after the restart; the check is **up** at the end; Freqtrade was unaffected throughout.
**Record:** T0, T_stop, alert arrival times and channels (paste/screenshot text of the alert), T_start, time the check went up, the
healthchecks.io *Log* tab for the check (copy the lines).

**If it fails / rollback**
- No alert by T0 + 20 min: record `FAIL`. Check the check's *Integrations* are attached to *this* check, the check's period/grace
  settings, and that the email is not in spam. **First `$C start conductor`** (do not leave it stopped while you investigate).
- Conductor will not come back: `$C up -d conductor`, then `docker logs ai-trading-agent-conductor --tail 80` (look for
  `CONFIG ERROR` or `STARTUP REFUSED`).
- Check still **down** 10 minutes after the restart: `docker exec ai-trading-agent-conductor python -m conductor.cli halts`
  (Conductor alive?), the check's *Log* for a `/fail` reason (the reason text says which health condition failed), and
  `HEALTHCHECK_PING_URL` in `.env`.

---

## Drill 5 — Backup and restore (already passed; record it)

**Proves:** the nightly B2 backup produces files that restore to a usable ledger and Freqtrade DB.
Runbook: [`restore-backup.md`](../06-runbooks/restore-backup.md) Part A. Drill 6 repeats it with real
data under pressure; this entry records today's pass.

**Do now:** paste into the chat the **full output** of today's run
(`scripts/restore-test.sh`, ending `RESTORE TEST PASSED`) and the `backup-now` output from the VPS if you have it.
It will go into the results file verbatim. Check it against the runbook's A5: `principal: 100 USD`, plausible row counts,
`stored:` recent, no `WARNING`.
(The run is dated 2026-10-04; `restore-test.sh` now also prints a `halts still active in this copy` line, which older output will not have.)

**Pass criteria:** `RESTORE TEST PASSED`, integrity `ok` for both files, principal `100 USD`, backup age under 36 h.
**If it fails:** see the runbook's Troubleshooting; do not proceed to drill 6 until this passes.
Cleanup after (A8): `unset RESTORE_B2_KEY_ID RESTORE_B2_APP_KEY`, delete the B2 `restore-test` key (drill 6 makes its own).

---

## Drill 6 — VPS rebuild from Terraform + cloud-init

**Proves:** the whole server can be destroyed and recreated from code and backups: same static IP, same Tailscale name and
dashboard URL, ledger and Freqtrade DB restored from B2 (principal, trades, **halts**), zero public inbound ports, and the
safety state (halt) intact on the new box.
**Procedure:** [`rebuild-vps.md`](../06-runbooks/rebuild-vps.md) — run it as written, step by step; this section
adds the drill's checkpoints and what to record. It uses `terraform apply -replace=hcloud_server.vps`, **never `destroy`**,
because `destroy` loses the static IP (needed for the Kraken whitelist later).

**Preconditions** (all must be true; the runbook's "Before you start" covers how)
- Drill 5 passed. You have a B2 **read** key (create it per `restore-backup.md` A2; you will delete it at the end) and
  `BACKUP_B2_BUCKET` / `BACKUP_B2_ENDPOINT` exported.
- On the Mac: `terraform`, `nmap`, `aws`, `sqlite3` installed; `infra/terraform/terraform.tfstate` and `terraform.tfvars` exist;
  `TRADING_MODE=dry_run` in the local `.env` (it is what `make push-env` ships).
- Tailscale admin console: HTTPS Certificates is enabled; you know whether your access rules name the VPS by `100.x` address.
- Branch merged and deployed (Setup above) so `main` has `make deploy-files` and `scripts/drill-check.sh`.
- Heads-up: healthchecks.io will alert about 15 minutes after Conductor goes down. That is expected here (it doubles as a re-test
  of drill 4); you will not have Conductor's Telegram bot until the new server is up.

**Timeline to record** (UTC): T_halt (kill switch engaged), T_backup, T_down (stack stopped), T_apply (Terraform
apply finished), T_tailnet (new node reachable), T_locked (port scan clean), T_restored (data in place, stack started),
T_halted_ok (`CHECK PASS` with the halt active), T_done. **RTO = T_halted_ok − T_down.**

**Checkpoints** (rebuild-vps.md step in brackets)
1. **Baseline** [Before you start 2, 4]: kill switch engaged (note the halt id `H`), `backup-now` shows both `ok`, `restore-test.sh all`
   passes and shows `halts still active in this copy: #H kill_switch`, IP and tailnet name/`100.x` noted, Terraform state copied.
   Run `scripts/drill-check.sh` on the VPS and keep the whole output (this is the "before").
   **Do not destroy anything until the restore test shows the halt.**
2. **Stop and insurance copy** [1, 2]: `down`, then the two tar copies. Expected: both listings non-empty.
3. **Tailscale: remove the old node** [3]: delete `ai-trader-vps` in the admin console; `tailscale status | grep ai-trader-vps` prints nothing.
   Create the **new** auth key (Reusable off, Ephemeral off, Expiry 1 day).
4. **Recreate, keep the IP** [4, 5A]: `plan -replace` shows `1 to add, 1 to change, 1 to destroy` and **no** primary-IP destroy; apply;
   `ipv4` equals the "before" IP. **Pass/stop point: if the IP changed, stop and record `FAIL`.**
5. **Tailscale side** [6, 6b]: cloud-init joins the new node with the new key; then
   (a) the name must be exactly `ai-trader-vps` (not `-1`); (b) update any access rule that names the old `100.x`
   address (this is the one that silently breaks `make ssh`); (c) `ssh-keygen -R` the old host keys; (d) revoke the auth key;
   (e) harden-host 12a/12b with the new `100.x`.
6. **Lock down and scan** [6]: `make vps-lockdown`, `make verify-lockdown` (four `OK:` lines), `nmap -Pn -p- -T4 <ip>` and the UDP scan
   from a different network (phone hotspot) with no exit node. Expected: nothing `open`. Save the scan output. **Pass/stop point.**
7. **Restore, then start** [7, 8]: `make push-env`, `make deploy-files`, `restore-test.sh all --keep`, `scp`, `up --no-start --build`, put the two DB files in,
   `up -d`, `scripts/drill-check.sh --watch 2`. Expected: `halts=1`, and `freqtrade` is `paused` from its first
   reachable moment and **never `running`** (it boots paused, and the restored ledger carries the halt).
8. **Verify restored** [8]:
   ```
   scripts/drill-check.sh --expect-state paused --expect-halts 1
   docker exec ai-trading-agent-conductor python -m conductor.cli capital
   docker exec ai-trading-agent-conductor python -m conductor.cli halts --all
   ```
   Expected: `CHECK PASS`; `principal: 100`; the `data` section equals the baseline (`principal=100 USD`, same `trades=`, `halts=` at least H,
   audit entries ≥ baseline); halt `#H kill_switch ACTIVE`. Dashboard `https://ai-trader-vps.<tailnet>.ts.net/` loads **at the same URL**
   from the phone over Tailscale, shows the old principal, and *Halts & audit* shows the pre-rebuild history. Telegram `/status` answers and
   shows the halt. `docker exec ai-trading-agent-conductor python -m conductor.cli backup-now` shows both `ok`.
   `sudo tailscale serve status` shows tailnet only; `sudo tailscale funnel status` shows no `(Funnel on)`.
9. **Lockdown re-verified after deploy** [provision-vps 22, 27, 29]: `sudo ss -tlnp | grep -v '127\.0\.0\.\|\[::1\]'` lists only `sshd` and
   `tailscaled`; `make verify-lockdown` again; the scan again (ports 22, 443, 8000, 8080 are the new ones to cover).
10. **Clear the drill halt** from Telegram: `/resume H`, `yes <CODE>`; `scripts/drill-check.sh --expect-state running --expect-halts 0` → `CHECK PASS`.
    (This also proves Telegram control works on the rebuilt server.)
11. Wait ~6 min: healthchecks.io is **up** again with a recovery notice. Cleanup per rebuild-vps.md step 9 (delete `~/vps-rebuild-backup`, the B2 read key, unset the env vars).

**Pass criteria (all):** same IPv4 before and after; node name `ai-trader-vps` and the same dashboard URL; restored ledger shows `principal 100 USD`,
trade count at least the baseline, the halt `#H` **active and enforced** (Freqtrade `paused` without anyone touching it); audit history intact;
no public port open in the scan, before and after the deploy; Telegram and dashboard reachable from the phone over Tailscale;
`backup-now` ok from the new server; heartbeat recovered. **Record:** the timeline, the before/after `drill-check.sh` output, `restore-test.sh`
output, the Terraform plan summary line and apply result, the `nmap` output (both), `tailscale status | grep ai-trader-vps`, the dashboard URL
(without the tailnet name if you prefer), the `--watch` lines from step 7, RTO, and every surprise.

**If it fails / rollback**
- **Before** step 4 (nothing destroyed yet): `$C up -d` on the old server, `clear-halt H`. Nothing lost.
- **After** the server is replaced there is no going back to the old box; recover forward. The data is safe in B2 and the insurance copy.
  - IP changed: record `FAIL`; do not continue to anything that depends on the IP; see rebuild-vps.md "primary IP".
  - Node came up as `ai-trader-vps-1` or `make ssh` fails right after joining: rebuild-vps.md step 6 / 6b.
  - cloud-init or Tailscale failed: public SSH from your IP is still open until you lock down; see rebuild-vps.md Troubleshooting. Do not lock down until the tailnet works.
  - `STARTUP REFUSED` on the restored ledger: do **not** start empty. Try the insurance copy (rebuild-vps.md Troubleshooting), then the previous night's B2 backup.
  - Scan shows an open port: run `make vps-lockdown` again and re-scan; if it persists, treat as an incident (provision-vps.md step 17).
- Re-running the whole drill is allowed. Mind Let's Encrypt's repeat-certificate limit for the same `ts.net` name (a handful per week): do not rebuild repeatedly in one day.

---

## Findings to review (not fixed by this work package)

These came out of reading the code while preparing the drills. None changes the drill procedures; each needs your decision.

1. ~~**Freqtrade boots `running` with a halt active.**~~ Resolved in this branch: Freqtrade boots `paused` and
   Conductor starts it only when no halt is active ([`ADR-0018`](../05-adr/0018-fail-closed-freqtrade-boot.md)). Drill 3
   proves it. Cost: if Conductor is down after a Freqtrade restart, no new entries until it is back (exits still managed).
2. **Drill 2 needs an open position, which Conductor cannot create.** It runs first for that reason. Real-exchange behaviour of cancel and force-exit (rejected orders, minimum sizes) cannot be exercised in dry-run at all: that
   remains a Phase 4 first-live-day check (TBD Phase 4).
3. **Tailscale access rules by address** go stale on every rebuild (documented now in `rebuild-vps.md` 6b and `security.md`). Using a Tailscale
   tag for the server instead would remove the manual step. Operator decision (tailnet policy).
4. **The 7-day soak clock** restarts at a rebuild. Hence the order above.
5. **Drills add halts and audit entries to the real ledger.** They are append-only by design, so they stay; the results file lists the halt ids so a
   reader of the audit log can tell drill halts from real ones.
