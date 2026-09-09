# ADR-0008: Quote all trading pairs in USD, not CAD

## Status

Accepted — 2026-09-09 (retroactively documented, work package 2F; the
decision itself was made and implemented in work package 2A —
`config.dry_run.json`'s `pair_whitelist`/`pair_blacklist` and
`stake_currency: "USD"` have used USD since that work package. This ADR
records the reasoning that was previously only sketched in
`docs/phase-2-plan.md` §1.)

## Context and problem statement

Kraken lists both USD- and CAD-quoted pairs for most major assets. The
$100 principal will ultimately be funded from a Canadian bank account via
Interac e-Transfer (a CAD-denominated action). Which quote currency should
the system actually trade against?

## Decision drivers

- Liquidity and pair breadth: does one quote currency offer materially
  deeper books and more available pairs than the other on Kraken?
- Fee-drag sensitivity at $100 scale (ADR-0005, risk register M4) — a
  thinner market means wider spreads, which is itself a hidden cost on
  top of the explicit taker fee.
- Compatibility with the tooling already in use — Freqtrade/CCXT support
  both, so this isn't a technical blocker either way.
- Simplicity: NFR6 requires CAD-equivalent fair value at time of fill for
  tax reporting regardless of which quote currency is traded, so trading
  in CAD directly doesn't avoid that conversion requirement — it just
  moves where the conversion step happens.

## Considered options

- **USD-quoted pairs** (e.g. `BTC/USD`)
- CAD-quoted pairs (e.g. `BTC/CAD`)
- A mix, chosen per-pair by whichever is more liquid

## Decision outcome

Chosen option: **USD for every whitelisted pair.** `config.dry_run.json`
sets `stake_currency: "USD"`; every pair in `pair_whitelist` is a `.../USD`
market (confirmed live and re-verified in
[`docs/research/02-kraken-market-facts.md`](../research/02-kraken-market-facts.md),
work package 2B — all 6 recommended pairs are USD-quoted).

### Rationale

- Kraken's USD pairs are consistently the deeper, more liquid market for
  every whitelisted asset — CAD pairs, where they exist at all, carry
  materially less volume and wider spreads on Kraken specifically. At
  $100 scale, spread cost matters as much as the explicit taker fee
  (ADR-0005's fee-economics argument applies equally to spread).
- NFR6 (CAD-equivalent tax reporting) is unaffected either way — a
  CAD-fair-value conversion is required for the ledger regardless of
  which currency the system actually trades in, since CRA reporting is
  always in CAD. Trading in USD does not create extra tax-conversion
  work that trading in CAD would have avoided; it just means the
  conversion step happens once, in the ledger, from a consistently
  liquid USD price series, rather than being implicitly baked into a
  thinner CAD order book's own pricing.
- One CAD→USD conversion happens once, at funding time (the Interac
  e-Transfer → Kraken CAD balance → convert to USD), rather than on every
  individual trade's pricing being subject to a thinner market.

### Consequences

**Good:**
- Deepest available liquidity and tightest spreads for every whitelisted
  pair, directly supporting the fee/spread-drag defence already
  established in ADR-0005.
- No change needed to Freqtrade/CCXT configuration beyond the quote
  currency string — no added technical complexity.

**Bad / accepted trade-offs:**
- Introduces one explicit CAD→USD conversion step at funding time (and
  implicitly, USD→CAD at eventual withdrawal/reporting) that a
  CAD-quoted approach would have avoided at the trading layer — accepted
  because NFR6's ledger-side CAD conversion is required either way, and
  funding-time conversion is a single, auditable, one-time event rather
  than something repeated on every trade.
- The system now carries incidental USD/CAD exchange-rate exposure on
  the principal itself, on top of the trading strategy's own exposure to
  the traded assets. This was not previously called out explicitly —
  added as risk register M8 in this same closure pass.

## More information

This decision does not change principal sizing (R1, $100 flat) or any
capital rule in `docs/02-requirements.md` — it only fixes which currency
`stake_currency` and the pair whitelist are denominated in.
