# Security policy

## Reporting a vulnerability

**Please don't open a public issue.** Report privately, either way:

- GitHub: this repository's **Security** tab → **Report a vulnerability** (private advisory), or
- e-mail **security@aplicy.com**.

Include what you found, how to reproduce it, and what you think the impact is. We aim to
acknowledge within **5 business days** and to agree on a disclosure date with you. There is no
bug bounty.

If you find a credential or other secret in this repository or its history, report it the same
way, and please don't use it.

## In scope

Security bugs, and also **trading-safety bugs**: anything that could make the system move money
in a way its rules forbid. For example:

- a path from LLM output, fetched data or a Telegram message to an exchange order (ADR-0003);
- anything that would let a key with withdrawal permission be accepted, stored or logged;
- a way to clear, bypass or lose a halt or kill switch without the documented human action;
- capital rules R1–R6 not enforced (sizing beyond principal, profit-fence errors, account
  isolation skipped);
- fail-open behaviour where fail-closed is documented (boot, key checks, venue checks);
- secrets leaking into logs, backups, the dashboard or error messages;
- escapes from the research sandbox (network access, writes outside its output);
- exposure of the dashboard or Freqtrade API beyond loopback or Tailscale.

## Out of scope

- Strategies that lose money. That is expected, and documented.
- Vulnerabilities in Freqtrade, ccxt, exchanges or other dependencies: report them upstream.
  Do tell us if our configuration makes one exploitable.
- Findings that need an already-compromised host or operator account.

## Supported versions

Only `main` is supported. There are no releases yet.

## For operators running this code

You are responsible for your own deployment. The minimum: exchange keys with **no withdrawal
or funding permission** and an IP whitelist, verified with the repository's access-check
scripts; secrets only in `.env` (git-ignored) and a password manager; the host reachable only
over a private network. See [`docs/04-architecture/security.md`](docs/04-architecture/security.md).
