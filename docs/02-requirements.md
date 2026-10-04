# 02 — Requirements

Format per requirement: **Statement**, **Rationale**, **Acceptance
criteria** (testable), **Verification method**. R1–R4 are the four capital
rules given in the Phase 1 brief; R5 is a follow-up isolation requirement;
R6 is a follow-up cost-ceiling requirement; NFRs follow.

---

## R1 — One-time $100 principal, never topped up

**Statement:** The system's principal is a single deposit of $100 (or
CAD-equivalent, see open question in research review §7.1). No further
deposits of the operator's funds are ever added to the trading account,
regardless of drawdown, opportunity, or strategy request.

**Rationale:** Bounds the maximum realistic loss to $100 and removes any
temptation — human or LLM-influenced — to "rescue" a losing position with
fresh capital, which is precisely the failure mode that turns a bounded
experiment into unbounded risk.

**Acceptance criteria:**
- AC1.1: Exactly one deposit transaction of $100 (or its CAD-equivalent at
  deposit time) exists in the exchange account's deposit history for the
  life of the project.
- AC1.2: The Conductor ledger has a hard-coded, immutable record of the
  principal amount and deposit date/tx id, set once at first funding.
- AC1.3: No code path in Conductor or Freqtrade configuration is capable of
  initiating a deposit to the trading account. (Deposits, like withdrawals,
  are a manual, out-of-band human action — see
  `04-architecture/security.md`.)
- AC1.4: A monthly reconciliation (manual or scripted, Phase 3+) confirms
  cumulative deposits to the trading account still equal the recorded
  principal.

**Verification method:** Exchange deposit-history export cross-checked
against the Conductor ledger's principal record; reviewed monthly per
`06-runbooks/`. Automated reconciliation job — TBD (Phase 3).

---

## R2 — Trading capital = principal + working profit only

**Statement:** At any point in time, the capital Freqtrade is permitted to
deploy (`stake_amount` / max open exposure) equals the original principal
plus **working profit** — profit that has not yet been fenced per R3 —
and nothing else.

**Rationale:** Keeps the system's own risk-of-ruin bounded to money it has
actually earned or was given, and makes the daily profit fence (R3) the
single mechanism that caps how much "house money" is ever at risk at once.

**Acceptance criteria:**
- AC2.1: `max_deployed_capital` (Conductor-enforced ceiling passed into
  Freqtrade's stake configuration) = principal + working profit, recomputed
  at least daily and immediately after every fencing event.
- AC2.2: Freqtrade's configured `stake_amount` / `tradable_balance_ratio`
  can never cause total exposure to exceed `max_deployed_capital`, verified
  by a unit test in the risk-engine wrapper (Phase 2+).
- AC2.3: Code review / static check prevents the Conductor from ever
  raising `max_deployed_capital` other than by the formula in AC2.1 — no
  manual override path in code.
- AC2.4: Fencing (R3) is a ledger-only operation with no exchange
  dependency, so it cannot fail the way a withdrawal could — but if the
  daily fencing job itself fails to *run* (e.g. host down at the UTC day
  boundary), any profit above the daily cap remains counted as working
  profit until the job successfully catches up. A missed fencing run is
  itself an alertable condition (see `06-runbooks/profit-sweep.md`), never
  a silent extension of available capital.

**Verification method:** Ledger audit comparing `max_deployed_capital` over
time against principal + (working profit as computed from realized P&L
minus fenced amounts); code review of the stake-sizing path; unit tests
(Phase 2+).

---

## R3 — Profit above the daily cap is fenced automatically, then moved manually to a key-less account

**Statement:** At the end of each trading day (UTC), Conductor computes
working profit and, if it exceeds a configured `daily_profit_cap`,
immediately **fences** the excess in the ledger — a ledger-only accounting
change that excludes it from `max_deployed_capital` (R2) so it is no
longer available for new positions. Fencing requires no exchange API call
and no withdrawal capability of any kind, consistent with NFR2: **the
running system never withdraws funds, ever.** The physical transfer of
fenced profit out of the trading account, to a separate account or wallet
the system holds **no API key for**, is a **manual, human-initiated
action** — performed by the operator directly on Kraken's own interface,
triggered when cumulative fenced-but-unmoved profit exceeds a configured
threshold (draft: **$25**) or once a calendar month has passed since the
last transfer, whichever comes first.

**Rationale:** The original design for this rule proposed an automated
daily withdrawal to a separate wallet. That directly contradicts NFR2 (the
exchange API key must never carry withdrawal permission) — a system that
can withdraw, even to one hardcoded destination it "can never reverse," is
a system with withdrawal capability, which is exactly the class of
capability NFR2 exists to rule out entirely, not merely constrain.
Fencing achieves the same protective intent — converting "the bot got
lucky today" into money the trading logic can never touch again — without
requiring any withdrawal capability: it is an accounting boundary inside
the ledger, not a fund movement. Physically moving fenced funds off the
exchange is deferred to a manual, periodic operator action; that action
exists for custody/realization reasons (getting the money somewhere the
operator controls directly), not for the risk-control purpose R2/R4
already need — fencing alone fully satisfies R2's "principal + working
profit only" ceiling the moment it happens, regardless of when the
physical transfer follows.

**Acceptance criteria:**
- AC3.1: A configured `daily_profit_cap` (exact value TBD (Phase 3), see
  `08-paper-exit-criteria.md` for related numeric gates) and a
  `manual_move_threshold` (draft: $25) exist in Conductor config, along
  with a monthly manual-move reminder cadence.
- AC3.2: A scheduled job runs once per UTC day, computes working profit,
  and if it exceeds `daily_profit_cap`, marks the excess as **fenced** in
  the ledger. This is a ledger state change only — no exchange API call of
  any kind is made, and no code path anywhere in this repository initiates
  a withdrawal (see NFR2, `CLAUDE.md` §0.2).
- AC3.3: Fenced profit is excluded from `max_deployed_capital` (R2) in the
  same computation cycle it is fenced — Freqtrade's stake sizing can never
  use fenced funds, even though they remain physically inside the trading
  account pending manual transfer.
- AC3.4: The physical transfer of fenced profit to the sweep destination
  is performed manually by the operator, directly on Kraken's own
  interface — never by code in this repository (same pattern as deposits,
  R1 AC1.3) — triggered when cumulative fenced-but-unmoved profit exceeds
  `manual_move_threshold` **or** one calendar month has elapsed since the
  last transfer, whichever comes first. Conductor alerts the operator when
  either trigger condition is met; it does not act on it.
- AC3.5: Every fencing event (amount, date) and every manual transfer
  (amount, destination, exchange tx id, timestamp, operator identity) is
  logged in the ledger, and each manual transfer is reconciled against the
  destination account's balance by the operator (see
  `06-runbooks/profit-sweep.md`).
- AC3.6: A missed daily fencing run (e.g. host down at the UTC day
  boundary) is itself an alertable condition — the job catches up and
  fences correctly on its next run, but the gap is never silently absorbed
  as if it didn't matter (see R2 AC2.4).

**Verification method:** Ledger audit confirming fenced profit is excluded
from `max_deployed_capital` the same day it crosses the cap; code review
confirming no exchange withdrawal call exists anywhere in Conductor
(NFR2); runbook execution log + destination-account balance reconciliation
for each manual transfer, reviewed by the operator; automated fencing-job
unit tests (Phase 3+).

---

## R4 — Hard loss limits halt trading and require human re-enable

**Statement:** The system enforces at least three independent hard loss
limits — **daily loss limit**, **max drawdown from peak equity**, and
**consecutive-loss breaker** — any one of which, when breached, halts all
new order entry immediately and requires an explicit human action to
resume. No automatic, timer-based, or LLM-initiated re-enable exists for
any of the three.

**Rationale:** This is the system's last line of defence against both
strategy failure and infrastructure failure (bad deploy, exchange anomaly,
runaway loop — see research review §4, Knight Capital reference). A halt
that can re-enable itself is not a hard limit.

**Acceptance criteria:**
- AC4.1: **Daily loss limit** — if realized + unrealized loss for the
  current UTC day exceeds a configured threshold (draft: −3% of trading
  capital, see `08-paper-exit-criteria.md`), new entries are blocked until
  a human re-enables (not merely until the next UTC day).
- AC4.2: **Max drawdown** — if equity falls a configured percentage below
  its running peak (draft: −10%), the system flattens open positions where
  safely possible and halts new entries, requiring human re-enable. See
  `06-runbooks/nuclear-protocol.md` for the flatten procedure.
- AC4.3: **Consecutive-loss breaker** — after N losing trades in a row
  (draft: N = 3, exact value TBD (Phase 3) per strategy backtesting),
  new entries for that strategy are blocked pending human review, even if
  neither the daily nor drawdown limit has been hit.
- AC4.4: All three checks are enforced in at least two independent layers
  — Freqtrade's built-in protections (StoplossGuard, MaxDrawdown,
  CooldownPeriod) **and** the Conductor's own check — so a bug or
  misconfiguration in one layer does not remove the control (defence in
  depth, per research review §4).
- AC4.5: A halt state persists across process restarts (stored in the
  ledger DB, not in memory) — restarting Freqtrade or Conductor must never
  silently clear a halt.
- AC4.6: Re-enabling requires an explicit, authenticated human action
  (Telegram command from an allow-listed operator, or equivalent) logged
  with timestamp and operator identity in the ledger.
- AC4.7: Every halt triggers an alert to the operator (Telegram) within
  the same monitoring cycle it occurs in — silence is itself an alertable
  condition (heartbeat, see `04-architecture/conductor.md`).

**Verification method:** Automated tests simulating each breach condition
against a test Freqtrade/Conductor instance in dry-run (Phase 2–3); manual
drill per `06-runbooks/kill-switch.md` and
`06-runbooks/nuclear-protocol.md` before first live allocation, and
thereafter on the re-validation cadence in `07-roadmap.md`.

---

## R5 — Account isolation

**Statement:** The system sizes positions only from the quote-currency
balance it can attribute to itself (principal + working profit, per R2);
the ledger reconciles only assets the system itself bought; and a startup
check aborts (does not proceed to trading) and alerts the operator if any
whitelisted pair already holds a balance the system did not itself
acquire.

**Rationale:** The Kraken account this system trades in is the operator's
own personal account, not a dedicated entity created solely for this
project — the operator may hold other crypto there, now or in the future
(personal holdings, gifts, past purchases). Without an explicit isolation
rule, pre-existing holdings could silently inflate the capital the system
believes it has (breaking R2's "principal + working profit only" ceiling)
or get sold by a strategy that has no idea those coins were never the
bot's to trade. This requirement makes that boundary a checked invariant,
not an assumption. See risk register M7.

**Acceptance criteria:**
- AC5.1: Position sizing (`max_deployed_capital`, R2) is computed only
  from the quote-currency (e.g. USD/USDT/CAD, per the currency decided in
  Phase 2) balance recorded in the Conductor ledger as belonging to the
  system — never from a raw "whatever the account currently holds" read of
  exchange balances.
- AC5.2: The ledger's reconciliation logic (R1 AC1.4, R2) only counts
  assets whose acquisition is recorded in the ledger as a system-initiated
  buy — an asset present in the account that the system did not itself buy
  is never treated as working profit or available capital.
- AC5.3: On every startup (and before the first trade after any restart),
  Conductor runs a balance check against the pair whitelist: for each
  whitelisted base asset, if the exchange-reported balance exceeds what
  the ledger's own buy history for that asset accounts for, the system
  **aborts startup** (does not begin or resume trading) and sends an
  alert identifying the pair and the unexplained balance.
- AC5.4: Clearing an AC5.3 abort requires an explicit human action
  (documented in a runbook — TBD (Phase 3), re-tagged from Phase 2: this
  is Conductor's own startup check, and Conductor does not exist until
  Phase 3, so there is nothing to write the clearance runbook against
  yet; extend `06-runbooks/start-stop.md`) that either records the pre-existing
  balance as explicitly excluded from the system's capital, or confirms
  it was moved out of the account before restart — never an automatic
  retry that just proceeds.
- AC5.5: This check applies per whitelisted pair, not just in aggregate —
  a balance discrepancy in one asset must not be maskable by a shortfall
  in another.

**Verification method:** Startup-check unit tests using a seeded exchange
balance that includes an untracked asset (Phase 2+); manual drill before
first live allocation confirming the abort actually blocks trading rather
than merely logging a warning; ledger audit cross-checking AC5.2 alongside
the existing R1/R2 reconciliation.

---

## R6 — Research-loop cost ceiling

**Statement:** The nightly LLM research loop operates under a configured
monthly token/spend budget. Conductor alerts the operator when cumulative
spend for the current calendar month reaches 80% of the budget, and
**hard-stops the research loop** (pauses generating new candidates) at
100% — the research loop pausing has **no effect on live/paper trading**,
which continues to operate entirely independently, per
[`ADR-0003`](05-adr/0003-llm-never-orders.md): the live path never depends
on the LLM being reachable or funded.

**Rationale:** The system's principal is capped at $100 (R1), but the LLM
research loop's compute/API cost is an ongoing expense that is not itself
bounded by the capital rules — a runaway or misconfigured nightly loop
could, in principle, cost far more over time than the money it manages
(see risk register L7). A monthly ceiling, tracked and enforced at the
timescale a human actually reviews spend, makes that cost bounded and
visible rather than an open-ended, easy-to-ignore line item.

**Acceptance criteria:**
- AC6.1: A configured `monthly_llm_budget` (draft value TBD (Phase 3))
  exists in Conductor config, tracked in the currency the LLM API bills
  in.
- AC6.2: Cumulative spend for the current calendar month is tracked from
  every logged prompt/response — reusing the logging NFR1 already
  requires for cost accounting, not a separate mechanism.
- AC6.3: At 80% of `monthly_llm_budget`, Conductor sends an alert
  (Telegram) — informational, no automatic action taken.
- AC6.4: At 100% of `monthly_llm_budget`, the research loop **hard-stops**:
  no further nightly runs are triggered until the next calendar month, or
  an explicit human override, logged with operator identity if used.
- AC6.5: A hard-stopped research loop does **not** halt, pause, or
  otherwise affect Freqtrade or any live/paper trading in progress —
  verified explicitly, since this is the one place a non-trading-path
  failure must be proven not to leak into the trading path.
- AC6.6: The budget resets automatically at the start of each calendar
  month (UTC), and the reset itself is logged.

**Verification method:** Unit test simulating spend crossing the 80%/100%
thresholds and confirming alert/hard-stop behaviour (Phase 3+); manual
drill confirming a hard-stopped research loop leaves live trading fully
unaffected; ledger audit of monthly spend vs. budget.

---

## Non-functional requirements

| ID | Requirement | Acceptance criteria (summary) | Verification |
|---|---|---|---|
| NFR1 | **Auditability / replayability** — every LLM prompt/response and every order-path decision is logged with enough fidelity to reconstruct why a trade happened. | Prompt/response logged with content hash; strategy versions pinned to git commit; ledger links each order to the strategy version and (if applicable) research-loop run that produced it. | Log/ledger review; replay of a sampled decision, Phase 3+. |
| NFR2 | **Key scoping** — the exchange API key used by the running system can never withdraw funds. | Key created with query + trade only, no withdrawal, IP-whitelisted (see `04-architecture/security.md`). | Verified at key creation and at each rotation (`06-runbooks/key-rotation.md`). |
| NFR3 | **Secrets hygiene** — no secret ever enters the git history. | `.gitignore` covers `.env`/keys; secrets live in env vars / LastPass only; pre-commit secret scan — gitleaks (`.pre-commit-config.yaml`, resolved Phase 2). | Pre-commit hook + manual review before first public push. |
| NFR4 | **Reliability / heartbeat** — a silent failure (host asleep, process crashed, network down) is detected, not just an active error. | Heartbeat signal expected on a fixed interval; alert fires on missed heartbeat. Exact interval TBD (Phase 3). | Manual drill: kill the process and confirm alert fires. |
| NFR5 | **Overfitting defence** — strategies promoted to paper/live are not curve-fit to backtest data. | ≤6 tunable parameters per strategy; anchored + rolling walk-forward validation; reject if out-of-sample Sharpe < 50% of in-sample Sharpe; conservative fee/slippage assumptions in backtests (research review §4). | Enforced in the promotion-gate code path (Phase 3), reviewed per strategy. |
| NFR6 | **Legal/tax record-keeping** — every trade produces a record sufficient for Canadian tax reporting. | Ledger stores CAD-equivalent fair value at time of each fill, cost basis, and disposition, exportable as a report. | Manual review with an accountant before first live trade with real profit; see `03-risk-register.md` T1–T2. |
| NFR7 | **Open-source readiness** — the repo is safe to make public at any commit. | No secrets, no PII beyond the operator's own attribution, licence present, docs coherent standalone. | Reviewed before each push if the repo is public; see `CLAUDE.md` §5. |
| NFR8 | **Maintainability** — every architectural change is traceable to a decision record. | ADR exists for any change to execution engine, exchange, order-authority model, host, frequency policy, or licence. | PR review checklist — TBD, genuinely blocked on there being a PR workflow at all: no git remote is configured yet (confirmed 2026-09-09, `git remote -v` empty), so there are no PRs to check against. Not a Phase 2 docs-closure blocker; revisit once a remote exists. |

## TBD summary

- Exact `daily_profit_cap` value and `daily_loss_limit` / `max_drawdown` /
  consecutive-loss thresholds beyond the drafts above — TBD (Phase 3), to
  be finalized in `08-paper-exit-criteria.md` before first paper run.
- ~~CAD vs USD principal/quote currency~~ — resolved Phase 2: USD, see
  [`ADR-0008`](05-adr/0008-usd-quote-currency.md).
- Heartbeat interval and alert channel timing — TBD (Phase 3).
- ~~Pre-commit secret-scanning tool choice~~ — resolved Phase 2: gitleaks
  (`.pre-commit-config.yaml`).
- R5 startup-abort clearance runbook (extending `06-runbooks/start-stop.md`)
  — TBD (Phase 3), re-tagged from Phase 2 (Conductor-dependent, see AC5.4
  above).
- R3 `manual_move_threshold` final value (draft $25) — TBD (Phase 3),
  confirm alongside `daily_profit_cap`.
- R6 `monthly_llm_budget` draft value — TBD (Phase 3).
