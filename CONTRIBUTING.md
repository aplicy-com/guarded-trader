# Contributing to Guarded Trader

Thanks for looking. This project values **not losing money by accident** above features, so
the bar for anything near the trading path is high. Docs fixes, tests, research tooling and
honest negative results are all very welcome.

## Hard rules (a PR that breaks one is closed, however good the rest is)

From [`CLAUDE.md`](CLAUDE.md) §0. They apply to people and AI assistants alike:

1. **The LLM never places, changes or cancels an exchange order.** Only the deterministic engine
   (Freqtrade) talks to order endpoints ([ADR-0003](docs/05-adr/0003-llm-never-orders.md)).
2. **No code may hold, log or transmit an exchange key with withdrawal permission.**
3. **No secrets in the repository**: no keys, tokens, `.env` files, real IPs, chat IDs or account
   IDs in code, tests, docs, issues or PR text. `.env.example` has empty values only.
4. **Capital rules R1–R6** ([`docs/02-requirements.md`](docs/02-requirements.md)) are hard
   constraints. Nothing may weaken a halt, a loss limit, account isolation, or fail-closed
   behaviour without a new ADR the maintainers have accepted.

## How changes are made

- **New here?** Start with a [good first issue](https://github.com/aplicy-com/guarded-trader/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22): each one is small, needs no
  exchange account or money, and stays away from the trading path.
- **Discuss first** for anything beyond a small fix: open an issue describing the problem.
- **Architecture changes need an ADR** in `docs/05-adr/` (MADR format, one decision per file,
  numbered). Supersede old ADRs; don't edit their decisions.
- **Operational procedures need a runbook** in `docs/06-runbooks/`: numbered steps, an expected
  output at each step, no "use your judgement".
- **Mark unknowns `TBD (Phase N)`.** Don't invent a number or a fact to fill a gap.
- **Diagrams are Mermaid**, in the Markdown file they document.

## Strategy proposals

A strategy is a hypothesis, and the hypothesis comes first.

1. Open a *Strategy proposal* issue with the hypothesis, the evidence for it, and **every**
   parameter value (≤ 6 tunable parameters).
2. Once agreed, it is added to `services/research/candidates.json` and committed **before** any
   backtest is run. Every registered run counts as a trial, pass or fail.
3. It is judged by Gate 1 as written ([`docs/08-paper-exit-criteria.md`](docs/08-paper-exit-criteria.md)):
   Tier-1 taker cost, walk-forward, random-entry null, trade-count and concentration rules.
   A failed candidate is a result, and it gets written up.

Please don't send tuned backtest screenshots. Untracked trials are exactly how overfitting
happens.

## Code standards

- Python 3.12+. Run before pushing:
  ```
  make conductor-test conductor-lint research-test research-lint
  pre-commit run --all-files      # includes gitleaks
  ```
- **Tests are mandatory for anything that touches money**: sizing, risk checks, ledger
  arithmetic, gate logic, profit fencing.
- Keep the services separate: no shortcut that puts LLM output and the live order path in the
  same code path.

## Commits and pull requests

- Branch off `main`; [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`), imperative mood.
- **Sign off every commit** (Developer Certificate of Origin, <https://developercertificate.org/>):
  `git commit -s`. By signing off you certify you have the right to submit the work under the
  project's licence.
- Contributions are licensed under **Apache-2.0** (inbound = outbound). No CLA.
- No `Co-Authored-By`/"Generated with" trailers. If an AI assistant helped, say so in the PR
  description; you are still responsible for every line.
- Fill in the PR template's safety checklist.

## Security issues

Never in a public issue. See [`SECURITY.md`](SECURITY.md).

## Conduct

[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) applies to every project space.
