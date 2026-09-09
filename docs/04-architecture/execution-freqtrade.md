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

Exact numeric thresholds for each protection mirror the values finalized
in [`08-paper-exit-criteria.md`](../08-paper-exit-criteria.md) and R4 —
TBD (Phase 2) until first configured.

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
  principal + working profit.
- Per-trade risk: 1–2% of equity, ATR-based sizing (research review §4) —
  exact % TBD (Phase 2) per strategy backtest.
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

- Exact per-pair minimum notional sizes on Kraken and whether they're
  compatible with $100-scale positions — TBD (Phase 2), see risk register
  E6.
- Quote currency (USD vs CAD pairs) — TBD (Phase 2), research review
  §7.1.
- Exact protection thresholds — TBD (Phase 2), pending
  `08-paper-exit-criteria.md` finalization.
