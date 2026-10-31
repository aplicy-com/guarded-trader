# ADR-0022: NDAX rejected as a live venue

## Status

Accepted — 2026-10-30. Does not supersede ADR-0002 (Kraken stays the designated exchange). Does
not change ADR-0003 or any capital rule.

## Context and problem statement

Kraken Tier-1 taker fees (0.80 %, ADR-0021) make every candidate so far lose money. Funding the
Kraken account for the live pilot (ADR-0019) has also not worked. NDAX, a Canadian exchange
with a flat 0.20 % fee, was checked as a replacement on branch `spike/ndax`
([`docs/research/06-ndax-feasibility.md`](../research/06-ndax-feasibility.md)). Can the system
trade live on NDAX without breaking CLAUDE.md §0?

## Decision drivers

- **CLAUDE.md §0 rule 2:** no code may hold an exchange key with withdrawal permission. We must
  be able to **prove** a key can't withdraw. Believing the UI isn't enough.
- **Stops must survive the bot.** The live config uses `stoploss_on_exchange` (ADR-0019), so an
  open position stays protected while Freqtrade is down.
- No account login or password may enter the bot's environment.

## Considered options

- **Reject NDAX for live** (chosen)
- Use NDAX with a key the UI calls "read-only/trade-only" and trust the UI (rejected: §0 rule 2
  asks for verification, and the API contradicts the UI, below)
- Use NDAX with the account login/password in the bot, as ccxt asks by default (rejected:
  holding the password is worse than holding a withdrawal-capable key)
- Patch Freqtrade for NDAX stops and keep probing the key (rejected for now: the key-scope gap
  can't be closed from our side)

## Decision outcome

NDAX will not be used for live trading. What decided it, from the read-only key check run on
the VPS on 2026-10-30:

1. **The key's withdraw scope can't be verified.** The documented API has no call that lists
   API keys or their permissions. It describes permissions only per user. The one permission
   report available, `GetUserPermissions` (undocumented, takes a `UserId`), returned
   `Deposit, Trading, Withdraw` for the read-only key's session. The only behavioural test is a
   Trading/Withdraw fee quote, and it came back `404 NOT FOUND`. NDAX's HTTP gateway gives the
   same answer to unauthenticated calls and to made-up endpoint names, so it proves nothing.
2. **Stops don't live on the exchange.** Freqtrade has no NDAX class and refuses
   `stoploss_on_exchange: true` for it. A stop would exist only while the bot runs.

Calling the API with the key alone (no login) does look possible: ccxt can be given the
numeric account id up front. That doesn't help with either point above.

### Consequences

**Good:**
- §0 rule 2 holds without exceptions. No unverified key ever reaches the trading path.
- The spike's tooling (`scripts/ndax-access-check.sh`, fail-closed probe) can be re-run as-is.

**Bad / accepted trade-offs:**
- The cheaper venue is off the table, so live trading stays paused (see `docs/07-roadmap.md`).
  At Kraken Tier-1 cost no candidate has passed Gate 1.
- NDAX's measured spread (35–91 bps) eats much of its fee advantage anyway, so less is lost
  than the headline fee suggests.

### Revisit if

All of these must hold:

- A re-run of `scripts/ndax-access-check.sh --scope read-only` shows `GetWithdrawFee`
  explicitly refused (`Not Authorized`, errorcode 20), **or** NDAX documents an API call that
  reports a key's own permissions;
- Freqtrade (or a reviewed adapter) supports exchange-held stops on NDAX; and
- a candidate passes Gate 1 at NDAX's real cost (fee plus measured spread).

## More information

- Spike write-up, including the VPS findings: `docs/research/06-ndax-feasibility.md`.
- Probe: `scripts/ndax_access_probe.py`, tests in
  `services/conductor/tests/test_ndax_access_probe.py`.
