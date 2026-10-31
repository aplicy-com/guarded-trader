# chore: add ruff hooks to pre-commit

Labels: good first issue,enhancement

## Context

`.pre-commit-config.yaml` only runs gitleaks. Lint problems surface later, in CI. Both Python
services already use ruff with their own settings (`services/*/pyproject.toml`).

## What to do

1. Add the official `astral-sh/ruff-pre-commit` hooks (`ruff-check` and `ruff-format`),
   pinned to the ruff version the services use (see `services/conductor/pyproject.toml`,
   `ruff==...`).
2. Make sure each service's files are checked with **that service's** config. Ruff finds the
   nearest `pyproject.toml` by itself, so check that this holds when running from the repo
   root.
3. Limit the hooks to `services/` for now. `scripts/` isn't lint-clean yet; that's a separate
   issue.

## Done when

- [ ] `pre-commit run --all-files` passes on `main`.
- [ ] Introducing an unused import in `services/conductor/src/` makes the hook fail.
- [ ] gitleaks still runs.
