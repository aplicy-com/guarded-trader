# ADR-0014: Conductor's write surface toward Freqtrade, and persisted halts

## Status

Accepted — 2026-10-05 (work package 3A-3). Consistent with, and an
application of, [`ADR-0003`](0003-llm-never-orders.md).

## Context and problem statement

Until 3A-2 Conductor only read from Freqtrade. 3A-3 needs it to act: pause
entries when a risk limit is breached, resume after a human decision, and
flatten on request. Any write path to a trading engine is a risk surface, and
ADR-0003 requires that no LLM can ever place, modify or cancel an order.

## Decision outcome

**1. A separate, allowlisted write client.** `FreqtradeControlClient` is a
distinct class from the read-only client. Its HTTP layer refuses, before
sending, anything except:

| Call | Purpose |
|---|---|
| `POST /stopentry` | pause new entries (Freqtrade `PAUSED` state) |
| `POST /start` | resume (the only thing that undoes `stopentry`) |
| `POST /stop` | stop the bot |
| `POST /forceexit` `{"tradeid":"all","ordertype":"market"}` | flatten |
| `DELETE /trades/{id}/open-order` | cancel one trade's open order |

No `forceenter` (Conductor never opens a position), no `reload_config` or other
config writes, no trade deletion. Tests assert the allowlist, including
forbidden paths paired with allowed body shapes, and an architecture test
asserts the client is imported only by the composition code, never by the LLM
or research code.

**2. Halts are facts in the ledger.** `halts` and `halt_clears` are
append-only (database triggers). A halt is active until a `halt_clears` row
exists; clearing needs a named operator. The ledger is written first, then
Freqtrade is told: a failed call can leave Freqtrade *more* restricted than the
ledger, never less.

**3. Re-application.** Freqtrade restarts "running". Every risk cycle (60 s) and
every Conductor startup re-sends `stopentry` to any halted instance whose state
is not `paused`/`stopped` (unknown state counts as running). If Freqtrade is
unreachable the failure is logged and retried; startup is never blocked by it.
Enforcement never resumes anything.

**4. Resume is human-only and fails closed.** `clear-halt` commits the clear,
then sends `start` only to instances no other active halt covers. A failed
`start` leaves Freqtrade paused; re-running the command retries it. A breach
that is still true simply re-halts on the next cycle.

**5. Nuclear order.** pause → cancel open orders → market `forceexit` all →
confirm flat → `stop`. `stop` is withheld if the account is not flat in time,
so an unmanaged position is never orphaned.

**6. Drawdown halts, it does not flatten (decided 2026-10-05).** R4 AC4.2 was
drafted as "flatten where safely possible and halt". Conductor does the halt and
the alert only. Open positions keep their own exits under Freqtrade; a human
decides whether to flatten (`/flatten` or `cli nuclear`). Rationale: an
automatic market exit triggered by a loss threshold sells into the conditions
that caused the loss, and removes the one moment a human reviews before capital
is liquidated. R4 is amended accordingly.

## Consequences

- R2 enforcement is by pausing entries only. The plan's idea of writing
  Freqtrade's `available_capital` and calling `/reload_config` is deliberately
  **not** done: it would add a config-write path.
- The Freqtrade container's own Telegram bot can still issue `/forceexit`,
  `/stop`, `/reload_config` (it is a separate process); 3A-4 disables it.
- Until 3A-4 the human actions are CLI commands run inside the container; the
  operator identity is the `--operator` argument, not cryptographic. Telegram
  allowlisted chat IDs improve this later.
- If Freqtrade `initial_state` were `paused` the 60-second re-apply gap after a
  Freqtrade restart would disappear, at the cost of Conductor having to start
  it; left as a possible follow-up.
