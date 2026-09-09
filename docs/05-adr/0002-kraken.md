# ADR-0002: Use Kraken as the exchange

## Status

Accepted — 2026-09-09

## Context and problem statement

We need one spot-crypto exchange to hold the $100 principal and execute
trades against. Which exchange?

## Decision drivers

- Must be usable by a Canadian retail individual without excessive
  friction.
- Must support API keys scoped to query + trade only, with withdrawal
  permission separately revocable and IP-whitelisting available.
- Must be supported by our chosen execution engine (Freqtrade via CCXT).
- Reasonable fee structure at very low volume (relevant given $100
  principal and fee-drag sensitivity — research review §5, risk register
  M4).
- Should have a credible security and operating track record; we are not
  chasing the lowest fee at the cost of custody risk.

## Considered options

- **Kraken**
- Coinbase (Advanced Trade)
- Binance (incl. Binance Canada considerations)
- A Canadian-only exchange (e.g. smaller local venues)

## Decision outcome

Chosen option: **Kraken**, spot trading, accessed by Freqtrade via CCXT.

### Rationale

- Explicitly supported and documented in the research review as the
  target exchange (§2, §4); Freqtrade/CCXT integration is a known-good
  path.
- API key model supports our required scoping: query + trade only, no
  withdrawal, IP whitelist (NFR2, `04-architecture/security.md`).
- Maker/taker fee tiers (~0.16%/0.26% at low volume on Kraken Pro per the
  research review) are workable, though still material at $100 scale —
  hence maker-preferred order placement and low-turnover strategies
  ([`0005-low-frequency-only.md`](0005-low-frequency-only.md)).
- Long operating history relative to newer venues.

### Consequences

**Good:**
- Well-trodden integration path via Freqtrade/CCXT reduces execution risk
  (E1 in the risk register).
- Key-scoping model directly supports our security requirements.

**Bad / accepted trade-offs:**
- Exact per-pair minimum order sizes and current fee tiers are not yet
  verified against $100-scale positions — **TBD (Phase 2)**, tracked as
  risk register E6.
- Kraken's regulatory/registration status in Canada is not yet verified
  as of this decision — **TBD (Phase 2)**, tracked as risk register T3.
  If that status changes materially before Phase 2 setup, this ADR should
  be revisited before funding the account.
- Quote currency (USD vs. CAD pairs) is not yet decided — **TBD (Phase
  2)**, research review §7.1.

## More information

This decision is specifically about the exchange, not about leverage or
margin products — Phase 1–4 use spot only, no margin, per the
low-frequency/no-leverage posture implicit throughout the risk register.
