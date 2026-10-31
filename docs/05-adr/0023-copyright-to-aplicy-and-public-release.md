# ADR-0023: Copyright to Aplicy Inc. and public release as `aplicy/guarded-trader`

## Status

Accepted — 2026-10-31. Supersedes the copyright holder in
[ADR-0006](0006-apache-2-licence.md). The licence stays Apache-2.0. Does not change any capital
rule or ADR-0003.

## Context and problem statement

ADR-0006 put the repository under Apache-2.0 with the original author's personal copyright,
and planned a transfer to Aplicy if the project went public. Live trading is now paused
(`docs/07-roadmap.md`, "Current status"). The platform, the gates and the negative results are
worth publishing as they are. Who holds the copyright, and what must happen before the
repository is public?

## Decision drivers

- One clear copyright holder for a public project, able to accept contributions and answer
  security reports.
- Publishing must not leak operational identifiers. The audit of 2026-10-31 found no secrets in
  any commit, but did find the VPS's IPv4, two Tailscale addresses, a personal e-mail in commit
  metadata and personal names in the docs.
- The record must stay honest: dates, pre-registration order and negative results kept intact.

## Considered options

- **Copyright to Aplicy Inc.; rewrite history to remove identifiers; publish `main` only**
  (chosen)
- Keep the personal copyright and publish under the Aplicy org (rejected by the operator)
- Publish a fresh single-commit history (rejected: it loses the dated commit trail that shows
  candidates were registered before they were run)
- Publish the history as it is (rejected: personal e-mail and server addresses)

## Decision outcome

- `LICENSE` and `NOTICE`: **Copyright 2026 Aplicy Inc.** The licence is still Apache-2.0.
  The legal assignment from the original author to Aplicy Inc. is a separate written document,
  outside this repository.
- **Name:** Guarded Trader, repository `aplicy/guarded-trader`.
- **History** is rewritten once with `git filter-repo`, before the first push:
  - the VPS IPv4 and the Tailscale addresses become documentation placeholders;
  - personal names in file contents become "the operator" / "the original author";
  - every commit's author and committer become the operator's GitHub no-reply identity;
  - `Co-Authored-By` trailers are removed (CLAUDE.md §2), and the README says openly that AI
    assistants were used.
  Commit dates are kept. The few hashes cited in the docs are updated, and the old→new table is
  in `docs/history-rewrite.md`.
- Only `main` is published. Feature branches stay in the private origin repository, which is
  kept unchanged as the archive.
- Contributions come in under Apache-2.0 with a DCO sign-off (`CONTRIBUTING.md`). Security
  reports go to security@aplicy.com or GitHub private vulnerability reporting (`SECURITY.md`).

### Consequences

**Good:**
- One accountable owner. A contribution and security process exists from the first public day.
- No operational identifier or personal e-mail is in the public history.

**Bad / accepted trade-offs:**
- Commit hashes differ from the private archive. Anyone checking a cited hash needs
  `docs/history-rewrite.md`.
- Older ADRs and docs now say "the operator" where they once named a person, which edits
  history text. This is accepted for privacy; the decisions themselves are unchanged.
- The VPS IPv4 was public information while the server ran. Removing it from the repo doesn't
  make it secret. It is being released or kept per `docs/06-runbooks/pause-and-resume.md`.

## More information

- Licence and third-party analysis: `NOTICE` (Freqtrade GPL-3.0, LGPL/MPL dependencies,
  vendored Chart.js and htmx, data sources).
- Audit method: gitleaks over all commits on all branches, plus a manual search of the full
  patch history for IPs, tailnet names, e-mails, chat IDs, account IDs, health-check URLs and
  bucket names.
