# ci: check Markdown links in docs

Labels: good first issue,enhancement

## Context

The docs are heavily cross-linked: ADRs, runbooks, research reports, drills. A rename breaks
links silently, and the history rewrite changed file contents across the repo.

## What to do

1. Add a CI job that checks links in all `*.md` files with
   [lychee](https://github.com/lycheeverse/lychee-action), pinned to a version.
2. Check **relative links and anchors** on every PR. Check external URLs on a weekly schedule
   only, so a flaky site can't block a PR.
3. Fix any broken links the first run finds, in the same PR.

## Done when

- [ ] The job passes on `main`.
- [ ] Renaming a doc that others link to makes the PR job fail.
- [ ] Placeholder URLs in runbooks (e.g. `https://ai-trader-vps.<tailnet>.ts.net/`) are
      excluded with a short comment explaining why.
