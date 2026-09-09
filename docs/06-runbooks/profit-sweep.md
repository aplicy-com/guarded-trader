# Runbook — Profit sweep (fence + manual move)

**What this does:** once per UTC day, Conductor automatically **fences**
working profit above `daily_profit_cap` in the ledger — a ledger-only
accounting operation that needs no exchange call and no API key
capability beyond what the system already has (query + trade only, see
NFR2). Fenced profit is immediately excluded from `max_deployed_capital`
(R2) and can never be used for new positions. Separately, **moving fenced
funds physically off the exchange is a manual action you perform
yourself**, on Kraken's own interface, whenever cumulative
fenced-but-unmoved profit crosses the configured threshold (draft: $25)
or once a month, whichever comes first — the system never initiates a
withdrawal, ever (R3, NFR2). This runbook covers verifying fencing
worked, performing the manual move, and handling either going wrong.

**When to use:** daily/periodic verification of fencing, performing a
scheduled manual move, or when you get a fencing-related alert.

## Routine verification — fencing (automatic, do this periodically)

1. Telegram: `/status` should show today's fenced amount (if any) and the
   running cumulative fenced-but-unmoved total.
2. Confirm fenced profit is reflected as excluded from
   `max_deployed_capital` — `/status` should show trading capital =
   principal + *unfenced* working profit only.
3. If a day passes with profit above `daily_profit_cap` and `/status`
   does **not** show a new fencing event, treat this as an incident (see
   "If fencing didn't happen when it should have" below) — don't assume
   it will "catch up on its own" without checking why.

## Performing a manual move (when threshold or monthly cadence is hit)

You'll get a Telegram alert when either condition is met: cumulative
fenced-but-unmoved profit exceeds the configured threshold (draft $25),
or a month has passed since the last transfer. **The alert is
informational — there's no urgency.** Fenced funds are already excluded
from trading capital and therefore already protected; this step is about
getting them off the exchange, not about risk control.

1. Log into Kraken directly (its own web/app interface — never through
   this system; the system holds no capability to do this step for you).
2. Check the current fenced-but-unmoved total via `/status`.
3. Manually initiate a withdrawal from the trading account to the sweep
   destination account, for the fenced amount, using Kraken's own
   withdrawal flow.
4. Record the transfer in the ledger (Conductor command for this: TBD
   Phase 3 — until it exists, note it manually somewhere you'll remember:
   amount, destination, and Kraken's transaction id).
5. Once initiated, verify per the reconciliation steps below.

## Routine verification — the manual move

1. Open the sweep destination account directly (its own login — the
   trading system holds no key for it, so this step can *only* be done by
   you).
2. Compare the balance/transaction history there against what you
   recorded as transferred in step 4 above.
3. If they match: done, nothing else to do.
4. If they don't match (destination shows less than expected): **do not
   assume it's a display delay** on the first check — wait a reasonable
   interval for exchange settlement (minutes to a few hours), check
   again. If still mismatched, treat this as an incident worth
   investigating with a clear head — it is **not** urgent (the fenced
   funds were already excluded from trading capital before you even
   initiated the transfer), but it is worth understanding.

## If fencing didn't happen when it should have

This is a different, more important failure than a delayed manual move —
fencing has no exchange dependency, so a missed fencing run almost always
means the Conductor process itself didn't run that day (e.g. host was
down at the UTC day boundary — see risk register O1).

1. Check Conductor's logs / `/status` for the gap.
2. Once Conductor is back up, the fencing job should catch up on its next
   scheduled run — verify this actually happened rather than assuming it.
3. Until it catches up, the un-fenced profit is still correctly counted
   as working profit under R2 (not lost, not miscounted) — just not yet
   protected from being risked on a new trade. This is a "fix it soon"
   issue, not a "the money is at risk of disappearing" issue, and there
   is no need to engage the kill switch over it alone.

## If a manual move itself fails

1. Read whatever error Kraken's own interface gives you (below minimum
   withdrawal, network error, destination rejected, etc.) — this is a
   normal exchange-side failure, not a system bug, since the system never
   initiates this step in the first place.
2. **This is not urgent.** Fenced funds are already excluded from
   `max_deployed_capital` regardless of whether the physical transfer
   succeeds — a failed manual move does not put trading capital at risk.
3. Retry when convenient, or wait until the next monthly cadence if the
   amount is small and the failure reason looks transient.
4. Do not "fix" a repeatedly failing move by adding an API key for the
   sweep destination to make it automatic — the entire point of R3 is
   that this account is unreachable by the running system. Fix whatever
   Kraken-side issue is blocking the manual transfer, not the isolation
   property itself.

## Why this matters enough to have its own runbook

Fencing is the mechanism that converts "the bot got lucky" into money the
trading logic can never touch again (R3 rationale), and it happens
automatically, with no exchange dependency, specifically so it can't fail
the way an automated withdrawal could. The manual move is a separate,
lower-urgency step for getting funds physically off the exchange — treat
a missed manual move as routine housekeeping, and a missed **fencing**
run as the thing actually worth investigating promptly.

## TBD

- Ledger export/verification tooling and a Conductor command to record a
  manual transfer — TBD (Phase 3).
- Exact `daily_profit_cap` and `manual_move_threshold` values — TBD
  (Phase 3), see `docs/02-requirements.md` R3 and
  `docs/08-paper-exit-criteria.md`.
