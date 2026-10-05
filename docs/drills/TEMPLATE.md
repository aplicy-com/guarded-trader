# 3A-6 drill results — YYYY-MM-DD

<!-- Copy this file to `results-YYYY-MM-DD.md` for a new run and fill it in. One file per
     session day; if a drill is re-run after a fix, add a new dated file and link it here. -->

**Operator:** the operator  
**VPS:** `ai-trader-vps`, dry-run, `TRADING_MODE=dry_run` confirmed: yes / no  
**Commit deployed** (`git rev-parse --short main` at deploy time): `        `  
**Procedures:** [`README.md`](README.md)

## Summary

| # | Drill | Result | Date | Notes |
|---|---|---|---|---|
| 1 | Kill switch via Telegram | NOT RUN | | |
| 2 | Nuclear via Telegram | NOT RUN | | |
| 3 | Restart persistence | NOT RUN | | |
| 4 | Heartbeat silence | NOT RUN | | |
| 5 | Backup + restore | NOT RUN | | |
| 6 | VPS rebuild | NOT RUN | | |

**3A exit-gate line this feeds:** "All six drills passed and recorded" — met only when every row above is `PASS` (a `PARTIAL` is not a pass).

**Baseline before the first drill** (`scripts/drill-check.sh` full output, plus `conductor.cli capital`, plus the Terraform `ipv4`):

```
(paste)
```

---

## Drill 1 — Kill switch via Telegram

**Tests:** `/kill` + `yes <code>` -> Freqtrade `paused` -> `/resume <id>` -> `running`

| Field | Value |
|---|---|
| Result | `NOT RUN` (PASS / FAIL / PARTIAL) |
| Date / operator | |
| Start – end (UTC), minutes | |
| Halt id(s) created (so the audit log can tell drill halts apart) | |

**Checklist (every pass criterion in [`README.md`](README.md)):**

- [ ] pass criteria all met
- [ ] outputs below are verbatim, unedited

**Record these (paste under each):**

- Negative checks (wrong code, expired) changed nothing: yes/no

  ```
  (paste)
  ```

- Halt id `#H`; time `/kill` sent / time `paused` showed (UTC)

  ```
  (paste)
  ```

- Output of `drill-check.sh --expect-state paused --expect-halts 1 --expect-positions <n>` (step 3)

  ```
  (paste)
  ```

- Telegram reply text for `/kill` confirm and `/resume` confirm (copy)

  ```
  (paste)
  ```

- Output of `drill-check.sh --expect-state running --expect-halts 0` (step 6)

  ```
  (paste)
  ```

**What surprised me / differed from the runbook:**

- 

**Follow-ups (runbook fixes, issues, decisions):**

- 

---

## Drill 2 — Nuclear via Telegram

**Tests:** `/flatten` -> orders cancelled, positions closed, bot stopped, halt persisted -> clear -> `running`

| Field | Value |
|---|---|
| Result | `NOT RUN` (PASS / FAIL / PARTIAL) |
| Date / operator | |
| Start – end (UTC), minutes | |
| Halt id(s) created (so the audit log can tell drill halts apart) | |

**Checklist (every pass criterion in [`README.md`](README.md)):**

- [ ] pass criteria all met
- [ ] outputs below are verbatim, unedited

**Record these (paste under each):**

- Variant: FULL (>=1 open position) / NO-POSITION; positions before: (id, pair, stake, open order?)

  ```
  (paste)
  ```

- Halt id `#H`; seconds from `yes` to the reply

  ```
  (paste)
  ```

- Telegram reply text (all steps)

  ```
  (paste)
  ```

- Output of `drill-check.sh --expect-state stopped --expect-halts 1 --expect-positions 0` (step 3)

  ```
  (paste)
  ```

- `conductor.cli halts` output (step 5) and `/trades` text (step 4)

  ```
  (paste)
  ```

- Output of `drill-check.sh --expect-state running --expect-halts 0` (step 7)

  ```
  (paste)
  ```

**What surprised me / differed from the runbook:**

- 

**Follow-ups (runbook fixes, issues, decisions):**

- 

---

## Drill 3 — Restart persistence

**Tests:** kill engaged; restart conductor, freqtrade, both (optional: host); still paused; clear

| Field | Value |
|---|---|
| Result | `NOT RUN` (PASS / FAIL / PARTIAL) |
| Date / operator | |
| Start – end (UTC), minutes | |
| Halt id(s) created (so the audit log can tell drill halts apart) | |

**Checklist (every pass criterion in [`README.md`](README.md)):**

- [ ] pass criteria all met
- [ ] outputs below are verbatim, unedited

**Record these (paste under each):**

- Halt id `#H`

  ```
  (paste)
  ```

- Step 2 (conductor restart) `CHECK PASS` output

  ```
  (paste)
  ```

- Step 3 `--watch` output (freqtrade restart) and **seconds `running` with halt active**

  ```
  (paste)
  ```

- Step 4 `--watch` output (both restart) and seconds `running` with halt active

  ```
  (paste)
  ```

- Step 5 host reboot: done / skipped; result

  ```
  (paste)
  ```

- Step 6 clear output and final `CHECK PASS`

  ```
  (paste)
  ```

**What surprised me / differed from the runbook:**

- 

**Follow-ups (runbook fixes, issues, decisions):**

- 

---

## Drill 4 — Heartbeat silence

**Tests:** conductor stopped -> healthchecks.io alert within grace -> restart -> recovery

| Field | Value |
|---|---|
| Result | `NOT RUN` (PASS / FAIL / PARTIAL) |
| Date / operator | |
| Start – end (UTC), minutes | |
| Halt id(s) created | n/a |

**Checklist (every pass criterion in [`README.md`](README.md)):**

- [ ] pass criteria all met
- [ ] outputs below are verbatim, unedited

**Record these (paste under each):**

- T0 (last ping), T_stop, T_start (UTC)

  ```
  (paste)
  ```

- Alert arrival per channel/device (time, text); minutes after T0

  ```
  (paste)
  ```

- Recovery notice arrival (time); time the check showed up again

  ```
  (paste)
  ```

- healthchecks.io *Log* tab lines for the window (copy)

  ```
  (paste)
  ```

- `docker ps` showing conductor `Exited` and freqtrade `Up` during the outage

  ```
  (paste)
  ```

**What surprised me / differed from the runbook:**

- 

**Follow-ups (runbook fixes, issues, decisions):**

- 

---

## Drill 5 — Backup + restore

**Tests:** `backup-now` -> `restore-test.sh` passes

| Field | Value |
|---|---|
| Result | `NOT RUN` (PASS / FAIL / PARTIAL) |
| Date / operator | |
| Start – end (UTC), minutes | |
| Halt id(s) created | n/a |

**Checklist (every pass criterion in [`README.md`](README.md)):**

- [ ] pass criteria all met
- [ ] outputs below are verbatim, unedited

**Record these (paste under each):**

- Full `scripts/restore-test.sh` output ending `RESTORE TEST PASSED`

  ```
  (paste)
  ```

- `backup-now` output (VPS)

  ```
  (paste)
  ```

**What surprised me / differed from the runbook:**

- 

**Follow-ups (runbook fixes, issues, decisions):**

- 

---

## Drill 6 — VPS rebuild

**Tests:** destroy/recreate from Terraform + cloud-init, restore from B2, redeploy, lockdown verified

| Field | Value |
|---|---|
| Result | `NOT RUN` (PASS / FAIL / PARTIAL) |
| Date / operator | |
| Start – end (UTC), minutes | |
| Halt id(s) created (so the audit log can tell drill halts apart) | |

**Checklist (every pass criterion in [`README.md`](README.md)):**

- [ ] pass criteria all met
- [ ] outputs below are verbatim, unedited

**Record these (paste under each):**

- Timeline (UTC): T_halt, T_backup, T_down, T_apply, T_tailnet, T_locked, T_restored, T_halted_ok, T_done; **RTO**

  ```
  (paste)
  ```

- IPv4 before / after (must be equal)

  ```
  (paste)
  ```

- Terraform plan summary line and apply result lines

  ```
  (paste)
  ```

- `tailscale status | grep ai-trader-vps` before and after (name must be exactly `ai-trader-vps`); dashboard URL unchanged: yes/no; old node deleted before apply: yes/no; ACL alias updated: yes/no/not needed

  ```
  (paste)
  ```

- `restore-test.sh all` output (pre-destroy) showing the halt, and the one used for the restore

  ```
  (paste)
  ```

- `drill-check.sh` full output BEFORE (baseline) and AFTER (step 8), side by side on the `data` lines

  ```
  (paste)
  ```

- `--watch` lines at first start (running -> paused window)

  ```
  (paste)
  ```

- `make verify-lockdown` and both `nmap` outputs (after lockdown; after deploy)

  ```
  (paste)
  ```

- `sudo ss -tlnp` filtered output, `tailscale serve status`, `tailscale funnel status`

  ```
  (paste)
  ```

- Phone: dashboard loads over Tailscale / not without it; Telegram `/status` and `/resume H` worked

  ```
  (paste)
  ```

- `backup-now` output from the new server; healthchecks.io back up (time)

  ```
  (paste)
  ```

**What surprised me / differed from the runbook:**

- 

**Follow-ups (runbook fixes, issues, decisions):**

- 

---

## Findings and follow-ups raised by this run

- 

## Sign-off

All six drills `PASS`: yes / no. Date: . Soak clock (7 days) started: .
