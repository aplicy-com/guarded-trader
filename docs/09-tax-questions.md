# 09 — Accountant question list (work package 2F)

This is a question list to bring to an accountant, not a set of answers.
Nothing in this document should be read as tax advice, and no code or
process decision in this repository should assume any particular answer
until an accountant has actually confirmed it in writing (per
`CLAUDE.md` §5 and risk register T1/T3/T4). This exists to make that
conversation efficient and complete, and to give NFR6 (ledger record-
keeping) a concrete target to build toward in Phase 3.

**Why now, not later:** Phase 2 is dry-run only — no real trade, no real
profit, no taxable event exists yet (see risk register T1/T4, re-tagged
during this closure pass to block **Phase 4 entry**, not Phase 2). The
question list is prepared now so the actual accountant meeting can happen
any time before Phase 4, without it becoming a last-minute blocker once
live capital is imminent.

## 1. Business income vs. capital gains classification

This is the single highest-impact classification question (risk register
T1) — it changes filing obligations, what expenses are deductible, and
how gains/losses are taxed, materially.

- Given the system trades automatically, at low frequency (2–3 open
  positions, 4h/1d bars, `ADR-0005`), with no manual per-trade decision by
  the operator once running — does CRA's "adventure or concern in the
  nature of trade" test point toward business income, or does the
  low-frequency, buy-and-hold-biased nature of the strategy (per
  `docs/05-adr/0005-low-frequency-only.md`) support capital gains
  treatment?
- Does the fact that trade decisions are made by deterministic code
  (Freqtrade) rather than the operator manually placing each order change
  this analysis at all — is "who/what makes the decision" relevant to CRA,
  or only "what the activity looks like from the outside" (frequency,
  intention, organization)?
- Does the presence of an LLM-driven research loop (Phase 3+, proposing
  and backtesting new strategy candidates, never itself placing orders —
  `ADR-0003`) change the classification analysis, even though the LLM has
  no order-placement authority?
- If classified as business income: what expenses are legitimately
  deductible (hosting/Docker infra costs, Anthropic API costs for the
  research loop, accountant fees themselves)?
- Can the classification differ for gains vs. losses, or does it have to
  be applied consistently to both?
- Once a classification is chosen (or CRA effectively forces one via
  audit/ruling), can it be revisited later if the system's behaviour
  changes materially (e.g. Phase 4 scaling, a materially different
  strategy mix)? Or does an initial election lock in a treatment?

## 2. Deemed acquisition cost of pre-2023 holdings on becoming a Canadian resident

This concerns the pre-existing personal crypto holdings already called
out across this repo (`docs/02-requirements.md` R5, and the held-asset
blacklist read directly from `services/freqtrade/user_data/config.dry_run.json`'s
`pair_blacklist`: **ACA, ADA, DOT, KAVA, SC, XTZ**) — acquired before
this project and explicitly excluded from anything the system trades or
sizes (R5 account isolation). Their tax cost basis is a separate question
from anything this system does.

- Subsection 128.1(1) of the Income Tax Act deems a new resident to have
  disposed of and immediately reacquired most property at fair market
  value on the date they became a Canadian tax resident. Does this apply
  to these specific holdings, and if so, what is the correct deemed
  acquisition date and FMV methodology for crypto assets specifically
  (which exchange/price source, what time-of-day convention, spot vs.
  volume-weighted)?
- **Bring to this meeting:** the actual date Canadian tax residency began,
  and whatever original acquisition records exist for each of ACA, ADA,
  DOT, KAVA, SC, and XTZ (purchase/receipt dates, amounts, and any
  available historical value) — this document deliberately does not
  assert any of these facts, since they aren't established anywhere in
  this repo and shouldn't be guessed at.
- Are there exclusions to the deemed-disposition rule that could apply
  here (e.g. property held for less than a certain period, or specific
  asset-class exclusions) — or is crypto squarely inside the general
  rule with no special treatment?
- If some of these assets were gifted rather than purchased (the
  blacklist description allows for this — "bought before this project,
  gifted, or otherwise not system-acquired") — does that change the cost
  basis analysis independent of the residency question?
- These assets stay entirely outside the trading system (R5) — does
  simply *holding* them (no disposition) create any reporting obligation
  before an eventual sale, or is nothing owed until disposition?

## 3. Record-keeping requirements

This maps directly to NFR6 (`docs/02-requirements.md`) — the ledger's
job is to produce records "sufficient for Canadian tax reporting," and
Phase 3's Conductor build needs a concrete target, not an assumption.

- What exact fields does CRA expect to be able to reconstruct for each
  disposition — cost basis (in CAD), proceeds (in CAD, at fill time),
  date/time, and anything else (e.g. superficial loss rule
  applicability, adjusted cost base tracking across multiple lots of the
  same asset)?
- For a strategy trading the same pair repeatedly (buy, sell, buy again),
  is adjusted cost base (ACB, average-cost method) the correct method for
  crypto specifically, the same as it would be for securities — or does
  crypto have different CRA guidance here?
- What FMV-in-CAD source/methodology is acceptable for each fill — the
  exchange's own fill price converted at a specific CAD/USD rate source
  and timestamp (risk register M8, `ADR-0008`)? Does CRA require a
  specific, defensible FX rate source (e.g. Bank of Canada daily rate) or
  is a reasonable market rate at time of trade acceptable?
- Fee treatment: are Kraken trading fees (taker ~0.26%, confirmed live in
  `docs/research/02-kraken-market-facts.md`) deductible, or do they adjust
  cost basis/proceeds directly?
- R3's profit-fencing/manual-move mechanism (`docs/02-requirements.md`)
  moves crypto (or its CAD-equivalent value) from the trading account to
  a separate, key-less account the operator controls directly — is this
  transfer itself a taxable disposition, or is it a non-taxable
  account-to-account movement (assuming no conversion to a different
  asset or to fiat happens at that point)? This directly affects whether
  R3's `manual_move_threshold`/monthly-transfer events need their own
  ledger tax-event flag distinct from the underlying trades.
- What retention period is required for these records, and in what
  format does CRA expect them presentable on request (raw export
  sufficient, or does it need to be a specific report format)?
- Is a professional crypto-tax software/service recommended for
  cross-checking the ledger's own CAD-equivalent calculations, or is an
  in-house ledger (as designed, NFR6) sufficient on its own?

## 4. GST/HST applicability

Lower-priority (risk register T4: Low/Low at $100 principal) but worth
settling once, rather than leaving unclear indefinitely if the project
ever scales.

- Does trading cryptocurrency for one's own account (not as a registered
  business providing a service to others) trigger any GST/HST
  registration or collection obligation at all?
- If classified as business income (see §1), does that change the
  GST/HST analysis, even though the "business" here has no
  customers/clients — it trades its own capital?
- Is there a revenue/threshold test that would only make this relevant
  if the project scales meaningfully beyond the current $100 principal
  (R1 forbids top-ups, so any scaling would be organic growth from
  trading profit, not new capital in)?
- Are exchange trading fees themselves subject to GST/HST in a way that
  matters here, or is that purely between Kraken and its own tax
  obligations?

## What this document is not

This is not a substitute for the actual meeting, and none of the
questions above should be treated as answered just because they're
written down clearly. Once the meeting happens, the outcome should be
recorded as a doc update (per `CLAUDE.md` §5 — "mark it `TBD (Phase N)`
until then") in `docs/03-risk-register.md` (T1/T4/T6 — T3 is the separate
Kraken-registration-status question, not a tax-classification one) and
`docs/02-requirements.md` (NFR6), not left only in an accountant's notes
or verbal confirmation.
