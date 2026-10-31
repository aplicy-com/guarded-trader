# ci: add Dependabot for GitHub Actions and Python dependencies

Labels: good first issue,enhancement

## Context

There's no automated update for the pinned GitHub Actions (`.github/workflows/ci.yml`) or the
`uv` lockfiles (`services/conductor/uv.lock`, `services/research/uv.lock`).

## What to do

Add `.github/dependabot.yml` with:

- `github-actions` for `/`, weekly;
- `uv` for `/services/conductor` and `/services/research`, weekly, grouped so minor and patch
  updates come as one PR per service.

## Done when

- [ ] The file validates (GitHub shows no error under *Insights → Dependency graph →
      Dependabot*).
- [ ] Ecosystem names and directories match the repository.

## Note for reviewers

Freqtrade and ccxt versions are pinned for compatibility (`CLAUDE.md` §3), and the Freqtrade
Docker image is pinned in `infra/docker-compose.yml`. Don't add the `docker` ecosystem in
this issue. Bumping those needs a backtest re-run and is a maintainer decision.
