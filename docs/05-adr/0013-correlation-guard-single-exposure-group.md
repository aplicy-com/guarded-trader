# ADR-0013: Correlation guard: the whole whitelist is one exposure group

## Status

Accepted — 2026-10-05 (work package 3A-3). Realises risk register M3.

## Context and problem statement

The dry-run paper run opened three positions at once across BTC, ETH, SOL,
LTC, XRP and LINK; they behaved as one bet. `max_open_trades: 3` therefore
overstated diversification. The design called for a correlation guard
(`docs/phase-3-plan.md` 3A-3, risk register M3) but not for its mechanism.

## Considered options

- **Whole whitelist = one group, hard cap of 2 positions** (chosen).
- Rolling-correlation grouping with a per-group cap: more precise, but needs
  price history, a threshold and tuning; none of that is justified for a $100,
  six-pair, low-frequency system, and the threshold would be an invented number.
- Keep 3 slots and rely on strategy behaviour: no control at all.

## Decision outcome

Treat every whitelisted pair as one exposure group and cap concurrent open
positions at `max_concurrent_positions` = 2, in two independent layers:

1. Freqtrade `max_open_trades` = 2 (`config.dry_run.json`).
2. Conductor counts open positions from the ledger every risk cycle; above
   the cap it persists a `max_positions` halt and pauses entries (ADR-0014).

Both numbers must agree; `.env.example` and the config comment say so. The
cap is a draft (R7 AC7.4); a correlation-based grouping is TBD (Phase 3,
with the research loop).

## Consequences

- At most 2 of the 6 pairs can ever be held, which also lowers turnover and
  the number of trades available for the 20-trades-in-8-weeks gate
  (`08-paper-exit-criteria.md`); that trade-off is accepted and should be
  re-examined with the Baseline4h/3B results.
- Fewer slots means a larger share of capital per trade under
  `stake_amount: unlimited`; R2 still bounds total exposure.
- Changing the number needs both settings changed together.
