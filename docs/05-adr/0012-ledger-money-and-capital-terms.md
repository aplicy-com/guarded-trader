# ADR-0012: Exact-decimal ledger storage and the capital-formula terms

## Status

Accepted — 2026-10-04 (work package 3A-2). Refines
[`ADR-0009`](0009-sqlite-ledger.md) (SQLite) without superseding it.

## Context and problem statement

3A-2 builds the ledger that every capital rule (R1–R5) and the tax export
(NFR6) depend on. Two choices were not settled by earlier documents:

1. **How money and time are stored in SQLite.** SQLite has no exact decimal
   type. A column declared `NUMERIC` gets numeric affinity, which stores
   `0.3` as a binary float; Python's `Decimal` then round-trips through
   `float` and silently loses exactness. For a ledger that is reconciled and
   used for tax records, that is unacceptable.
2. **What "working profit" means in the R2 formula.** The plan writes
   `max_deployed_capital = principal + working_profit − fenced`, while R2 defines
   working profit as profit *not yet fenced*. Read literally together, fenced
   profit would be subtracted twice.

## Decision outcome

### Storage

- Money is a Python `Decimal` end to end and is stored as canonical decimal
  **TEXT** (`format(d, "f")`). Floats and non-finite values are rejected at
  the persistence boundary. Sums are done in Python `Decimal`, never in SQL.
- Timestamps are timezone-aware UTC, stored as fixed-width ISO-8601 TEXT;
  naive datetimes are rejected. Calendar days (fence day, FX day) are
  `YYYY-MM-DD` TEXT.
- `principal`, `fence_events`, `manual_transfers` and `audit_log` are
  append-only, enforced by database triggers that abort `UPDATE`/`DELETE`
  (R1 AC1.2 "immutable once set"; AC3.5 auditability). Migration `0002` has no
  downgrade: dropping the ledger would destroy the audit trail, so recovery
  is "restore from backup".

### Capital terms (one definition, used everywhere)

- `realized_profit` — cumulative realized P&L of closed trades, fees included.
- `fenced_total` — cumulative profit fenced by R3.
- `working_profit = realized_profit − fenced_total`.
- `max_deployed_capital = max(0, principal + working_profit)`, i.e.
  `principal + realized_profit − fenced_total`. Fenced profit is subtracted
  exactly once.
- Fence rule (R3): `fenced = max(0, working_profit − daily_profit_cap)`. The
  cap's value remains **TBD (Phase 3)**; unset means nothing is fenced.

## Consequences

- Exactness and auditability, at the price that SQL cannot aggregate or order
  money columns; at this scale (a few dozen rows a day) that is irrelevant.
- Any future arithmetic on ledger money must go through `Decimal`; the
  `Money` column type enforces this.
- If the plan's literal formula was intended with `working_profit` meaning
  *gross* realized profit, the two are the same number; only the naming differs.
