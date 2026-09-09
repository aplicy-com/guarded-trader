# Runbook — Profit sweep

**What this does:** once per UTC day, Conductor computes working profit
and, if it's above the configured `daily_profit_cap`, transfers the excess
to the sweep destination account — an account/wallet the running system
holds **no API key for** (R3). This is normally fully automated; this
runbook covers verifying it worked and handling failures.

**When to use:** daily/periodic verification, or when you get a "sweep
failed" alert.

## Routine verification (do this periodically, not just on failure)

1. Telegram: `/status` should include the timestamp and amount of the
   last successful sweep.
2. Open the sweep destination account directly (its own login — remember,
   the trading system cannot reach it, so this step can *only* be done by
   you, manually, outside the system).
3. Compare the balance/transaction history there against the ledger's
   record of swept amounts.
   - Ledger export mechanism: TBD (Phase 3) — until implemented, check via
     `/status` or the Conductor DB directly.
4. If they match: done, nothing else to do.
5. If they don't match (destination shows less than the ledger claims was
   swept): **do not assume it's a display delay** on the first check —
   wait a reasonable interval for exchange settlement (minutes to a few
   hours depending on asset), check again. If still mismatched after that,
   treat this as an incident — the ledger's belief about swept funds is
   wrong, which is a data-integrity problem worth investigating with a
   clear head, not at 2am unless something else is also wrong.

## If you receive a "sweep failed" alert

1. Read the alert message for the specific reason given (e.g. "below
   exchange minimum withdrawal", "network/API error", "destination
   address rejected").
2. **This is not urgent** — per R3 AC3.5, a failed sweep does not silently
   retry into unbounded working profit; it fails closed. The money is
   still safely inside the trading account, just not yet moved. No
   position or capital is at risk because of a failed sweep by itself.
3. If the reason was "below minimum withdrawal": no action needed until
   enough profit accumulates to clear the minimum on a future sweep —
   confirm this is genuinely a small, expected amount via `/status` before
   dismissing it.
4. If the reason was a network/API error: check Kraken's status page and
   your host's network connectivity. If Kraken itself is down, this
   resolves itself on the next scheduled sweep attempt once Kraken
   recovers — no manual retry needed unless the alert repeats across
   multiple days.
5. If the reason was "destination address/account rejected" or anything
   that sounds like a **configuration** problem (not a transient
   condition): this needs a human fix before the next sweep can succeed.
   - Check the sweep destination configuration (TBD Phase 3 — exact config
     location to be documented once implemented).
   - Do not "fix" this by weakening the sweep destination's isolation
     (e.g. do not add an API key for it to make automation easier) — the
     entire point of R3 is that this account is unreachable by the running
     system. Fix the configuration error, not the isolation property.
6. Once you believe the issue is fixed, either wait for the next scheduled
   sweep or trigger one manually if that control exists (TBD Phase 3 —
   document the manual-trigger command here once implemented).
7. Confirm resolution via the routine verification steps above once the
   next sweep completes.

## Why this matters enough to have its own runbook

The sweep is the mechanism that converts "the bot is up on paper" into
actually-protected, actually-realized gains (R3 rationale). A silently
broken sweep doesn't lose money directly, but it quietly defeats the whole
point of the daily cap — working profit just keeps sitting inside
`max_deployed_capital` (R2), exposed to the next bad trade instead of being
protected. Treat repeated sweep failures as a priority to fix, even though
no single failure is an emergency.

## TBD

- Ledger export/verification tooling — TBD (Phase 3).
- Manual sweep-trigger command — TBD (Phase 3).
- Exact `daily_profit_cap` value — TBD (Phase 3), see
  `docs/02-requirements.md` R3 and `docs/08-paper-exit-criteria.md`.
