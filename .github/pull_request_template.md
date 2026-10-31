## What and why

<!-- Link the issue / ADR. Conventional-commit title. -->

## Safety checklist (CLAUDE.md §0)

- [ ] No path from LLM output, fetched data or a chat message to an exchange order (ADR-0003).
- [ ] No key with withdrawal or funding permission is requested, stored, logged or accepted.
- [ ] No secrets, real IPs, chat/account IDs or `.env` content in code, tests, docs or this PR.
- [ ] Capital rules R1–R6, halts, account isolation and fail-closed behaviour are unchanged, or
      changed by an accepted ADR linked above.
- [ ] Anything touching money (sizing, risk checks, ledger, gates, fencing) has unit tests.
- [ ] Architecture change → ADR added; new operational procedure → runbook added.
- [ ] `make conductor-test conductor-lint research-test research-lint` and
      `pre-commit run --all-files` pass.
- [ ] Commits are signed off (`git commit -s`).

## AI assistance

<!-- Did an AI assistant help? Say which parts. You remain responsible for every line. -->
