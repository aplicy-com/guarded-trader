# docs: point NFR8's verification at the PR template

Labels: good first issue,documentation

## Context

`docs/02-requirements.md`, row **NFR8** (Maintainability), says its verification method is
"PR review checklist — TBD", blocked because "no git remote is configured yet". That is no
longer true: the repository is on GitHub and `.github/pull_request_template.md` has a safety
checklist that includes "Architecture change → ADR added".

## What to do

1. Rewrite the *Verification* cell of NFR8 to name the PR template's checklist item, with a
   relative link.
2. Remove the stale "no git remote" sentence.
3. If the "TBD summary" further down lists NFR8, update it too.

## Done when

- [ ] NFR8 no longer says TBD or mentions a missing remote.
- [ ] The link resolves on GitHub.
- [ ] No other requirement row changes.

## Out of scope

Changing the requirement itself, or the PR template. Docs-only, about 5 lines.
