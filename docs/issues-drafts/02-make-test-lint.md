# build: add `make test` and `make lint` that run both services

Labels: good first issue,enhancement

## Context

To check everything before a PR you currently type four targets (README, CONTRIBUTING):
`make conductor-test conductor-lint research-test research-lint`.

## What to do

1. In the `Makefile`, add `test` (runs `conductor-test` and `research-test`) and `lint` (runs
   `conductor-lint` and `research-lint`) as prerequisites-only targets. Add both to `.PHONY`.
2. Use them in the README's quick start and in `CONTRIBUTING.md` ("Run before pushing").
3. Optionally use them in `.github/workflows/ci.yml`, keeping one job per service so failures
   stay easy to read.

## Done when

- [ ] `make test` and `make lint` pass on a clean clone, with no `.env`.
- [ ] A failure in either service makes the target exit non-zero.
- [ ] README and CONTRIBUTING mention the new targets.

## Hints

Make stops at the first failing prerequisite unless run with `-k`. That's fine here.
