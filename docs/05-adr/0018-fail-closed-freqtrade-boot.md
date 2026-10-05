# ADR-0018: Freqtrade boots paused; Conductor starts it only when no halt is active

## Status

Accepted — 2026-10-05 (follow-up to work package 3A-6). Amends point 3 and
point 4 of [`ADR-0014`](0014-conductor-write-surface-and-halt-state.md), which
recorded this as an open option ("If Freqtrade `initial_state` were `paused`...").
ADR-0014 stays as written; where they differ, this ADR wins.

## Context and problem statement

Freqtrade always boots in the state its config's `initial_state` names, and it
does not remember that it was paused. With `initial_state: running`, a Freqtrade
restart under an active halt (a crash, a host reboot, an unattended upgrade, a
deploy) left the bot able to open positions until Conductor's next 60-second risk
cycle re-sent `stopentry`. In dry-run that is harmless; with real money it is a
window in which a restarted bot can trade under a halt that is supposed to be
absolute. The 3A-6 restart drill was going to measure that window; closing it is
better.

## Decision outcome

1. **Freqtrade boots `paused`.** `initial_state: "paused"` in
   `services/freqtrade/user_data/config.dry_run.json`. Verified against the pinned
   image `freqtradeorg/freqtrade:2026.8`: `paused` is in the config schema's enum
   and maps to `State.PAUSED`; in that state the bot **does not enter** (entries
   run only when `state == RUNNING`) but **keeps processing exits** of open
   positions (stop-loss, ROI, trailing). That is why `paused` is used and not
   `stopped`: a `stopped` bot manages nothing, so open positions would sit
   unprotected until someone started it.
2. **Only Conductor starts it, and only with no halt.** `application/boot.py`
   (`start_if_clear`) runs at the end of each risk cycle, after ingest, risk
   evaluation and `enforce_halts`. For an instance whose Freqtrade has just booted
   it sends `start` if and only if (a) it is `paused`, (b) no active halt covers
   it, and (c) equity is known (every instance's ingest succeeded, so R4 could be
   evaluated). A boot is: Conductor's first successful look at the instance after
   Conductor starts, or a change in Freqtrade's `/health` `bot_startup_ts`
   (reset by Freqtrade every time it boots). A start that cannot be sent (API
   unreachable, `start` failed) stays pending and is retried every cycle.
3. **A halt always wins.** Under an active halt the start is withheld and not
   retried; the human `clear-halt` / `/resume` path starts the bot as before
   (ADR-0014 point 4, unchanged). The halts are re-read immediately after `start`;
   if one appeared in between (a `/kill` landing in that instant), the pause is
   re-applied at once rather than at the next cycle.
4. **Only `paused` is ever started.** A `running` bot is left alone; a `stopped`
   bot (nuclear, or a person) is left alone; an unknown state is never guessed at.
   A bot that is paused with the *same* startup marker, i.e. not freshly booted, is
   left alone too (so a pause by anything other than a boot is not undone).

## Consequences

- **Between a Freqtrade boot and Conductor's decision the bot cannot open a
  position.** After a restart under a halt there is no window at all: it boots
  paused and stays paused. The restart drill (drill 3) now checks that the state is
  never `running` during a restart with a halt active.
- **If Conductor is down, Freqtrade stays paused after any restart:** no new
  entries, exits still managed. Trading is down until Conductor is back. This is
  the intended failure direction, and the heartbeat alert (3A-5) is what tells
  you Conductor is down. A fresh deploy now shows Freqtrade `paused` for up to one
  risk interval after Conductor starts.
- **R4's "a human must re-enable" is unaffected.** This never starts a bot under a
  halt. It only restores the state "no halt, so trading" after a process restart,
  which a person never paused.
- `FreqtradeController.resume()` now has a second caller (docstring updated). The
  write allowlist is unchanged (`/start` was already on it).
- A Freqtrade `/reload_config` or a `stopped → running` transition also resets
  `bot_startup_ts` and so triggers one harmless re-evaluation. Conductor does not
  call `/reload_config`.
- Fixture caveat: `tests/fixtures/freqtrade/health.json` is hand-written from the
  2026.8 source, not recorded; re-record it from the VPS (see the fixtures README).
