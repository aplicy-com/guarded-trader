# Architecture — Execution (Freqtrade)

Freqtrade is the sole component permitted to place, modify, or cancel
orders (see [`ADR-0001`](../05-adr/0001-freqtrade.md),
[`ADR-0003`](../05-adr/0003-llm-never-orders.md)). It runs in Docker,
talks to Kraken via CCXT, and is driven entirely by config and pinned
strategy files that Conductor writes — it never calls out to Claude,
Telegram, or the sweep destination itself.

## Dry-run vs. live

Freqtrade's dry-run mode exercises the exact same code path as live
trading — strategy signal generation, order sizing, protections — but
simulates fills against real market data instead of sending orders to
Kraken. This is why the research review (§2) treats dry-run as "our 3-week
paper gate with zero code change": the paper stage in
[`08-paper-exit-criteria.md`](../08-paper-exit-criteria.md) is not a
separate simulator, it is Freqtrade in `dry_run: true`.

| | Dry-run (paper) | Live |
|---|---|---|
| Orders | Simulated against real market data | Real, sent to Kraken |
| Strategy code path | Identical | Identical |
| Config flag | `dry_run: true` | `dry_run: false` |
| `stake_amount` source | Simulated wallet, seeded to match `max_deployed_capital` | Conductor-computed `max_deployed_capital` (R2) |
| Used for | Backtest→WF-passed strategies, 3-week paper stage | 25% then 100% allocation stages only |

Switching a strategy from dry-run to live is a Conductor-issued config
change following a promotion-gate pass — never a manual edit made in a
hurry. See [`06-runbooks/start-stop.md`](../06-runbooks/start-stop.md).

## Built-in protections enabled

Per the research review's risk-control table (§4), the following Freqtrade
[protections](https://www.freqtrade.io/en/stable/plugins/#protections) are
enabled as the *first* of two independent layers for R4 (the Conductor
risk-limit checker, [`conductor.md`](conductor.md), is the second):

| Protection | Purpose | Maps to |
|---|---|---|
| `StoplossGuard` | Halts a pair after N stop-losses in a short window | R4 consecutive-loss breaker (AC4.3) |
| `MaxDrawdown` | Halts trading when equity drawdown from peak exceeds a threshold | R4 max drawdown (AC4.2) |
| `CooldownPeriod` | Forces a pause after a protection trips, before re-evaluation | Supports AC4.6 (no silent auto-resume) |
| `LowProfitPairs` | Locks out a pair whose recent trades show low/negative average profit | Overfitting/regime-shift defence (M5, NFR5) |

Protections are configured in the **strategy**, not `config.dry_run.json` —
Freqtrade 2026.8 deprecated the config-level `protections` key, and the
config now rejects it outright at startup. Each strategy file sets its own
`protections` class attribute (see
`services/freqtrade/user_data/strategies/Baseline4h.py`), so protection
tuning travels with the strategy version it was validated against, same as
`minimal_roi`/`stoploss`.

Exact numeric thresholds for 3 of the 4 protections are resolved (work
package 2C): `Baseline4h`'s `protections` class attribute sets
`CooldownPeriod` (2 candles), `StoplossGuard` (3 stops / 6 candles →
3-candle lock), and `MaxDrawdown` (10% over 48 candles → 3-candle lock).
`LowProfitPairs` is **not yet configured** — it needs real trade history
to set a meaningful "low profit" threshold against, which doesn't exist
yet for a strategy that has only been backtested, never run live/dry-run.
Re-tagged TBD (Phase 2D) — configure once work package 2D's dry-run has
produced enough trades to calibrate a threshold, rather than picking an
arbitrary number now.

## Strategy versioning

- Every strategy file that has passed backtest+walk-forward is committed
  to git; Freqtrade is pointed at a specific commit hash, never a mutable
  "latest" pointer.
- The Conductor ledger records which git hash is active for each stage
  (paper / 25% / 100%) at all times.
- A promotion or demotion is a config change (which hash Freqtrade loads),
  never a live edit of running strategy code.

## Position and risk sizing

- `max_open_trades`: 2–3 (research review §4), enforced alongside
  Conductor's correlation guard (risk register M3) so BTC+ETH open
  together still count as one effective exposure unit for risk-budget
  purposes.
- `stake_amount` / `tradable_balance_ratio`: derived from
  `max_deployed_capital` (R2), never a fixed number that could drift above
  principal + working profit, and computed only from ledger-recorded,
  system-bought balances (R5 account isolation) — never from a raw read of
  whatever the exchange account currently holds.
- Startup balance check (R5): before Freqtrade is allowed to trade, or
  resume trading after a restart, Conductor verifies that no whitelisted
  pair holds an exchange balance beyond what the ledger's own buy history
  explains. Any discrepancy — e.g. a pre-existing personal holding in a
  pair the strategy also trades — aborts startup and alerts the operator
  rather than letting the system size positions off, or potentially sell,
  a balance it never bought. See risk register M7 and
  `06-runbooks/start-stop.md` (TBD Phase 3 extension for clearing this
  abort — re-tagged from Phase 2, this is Conductor's own check and
  Conductor doesn't exist until Phase 3).
- Per-trade risk: 1–2% of equity, ATR-based sizing (research review §4) —
  **not implemented as designed in work package 2C.** `Baseline4h` uses
  Freqtrade's default equal-weight `stake_amount: unlimited` across up to
  3 open slots (`config.dry_run.json`), not true per-trade %-of-equity
  ATR sizing — kept simple deliberately for a path-validation baseline
  (`docs/research/03-baseline-backtest.md`). ATR is used for the *stop
  distance*, not position *size*. Re-tagged TBD (Phase 3) — real
  %-risk sizing is more naturally Conductor's `max_deployed_capital` (R2)
  computation, or a deliberate revision to a future promoted strategy, not
  a Phase 2 baseline concern.
- Timeframe: 4h/1d bars only, no tick-level or sub-hourly strategies (see
  [`ADR-0005`](../05-adr/0005-low-frequency-only.md)).
- Order preference: maker where the strategy allows, to minimize fee drag
  at $100 scale (M4 in the risk register).

## Licensing note

Freqtrade is GPL-3. We run it as a separate service (its own Docker
container) and interact only via its REST API — this repository's own code
is not a derivative work of Freqtrade and remains under Apache-2.0 (see
[`ADR-0006`](../05-adr/0006-apache-2-licence.md)).

## TBD

- ~~Exact per-pair minimum notional sizes on Kraken~~ — resolved,
  `docs/research/02-kraken-market-facts.md` (see risk register E6).
- ~~Quote currency (USD vs CAD pairs)~~ — resolved: USD, see
  [`ADR-0008`](../05-adr/0008-usd-quote-currency.md).
- Exact protection thresholds — resolved for 3 of 4 (`CooldownPeriod`,
  `StoplossGuard`, `MaxDrawdown`, see "Built-in protections enabled"
  above); `LowProfitPairs` TBD (Phase 2D).
- Per-trade %-risk ATR position sizing — not implemented, TBD (Phase 3),
  see "Position and risk sizing" above.
- R5 startup-abort clearance runbook — TBD (Phase 3), see "Position and
  risk sizing" above.
