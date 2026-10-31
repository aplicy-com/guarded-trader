# ci: run shellcheck on scripts/*.sh

Labels: good first issue,enhancement

## Context

`scripts/` holds 8 shell scripts, several run on the server during drills (`drill-check.sh`,
`restore-test.sh`, `harden-host.sh`). Nothing checks them automatically.

## What to do

1. Run `shellcheck scripts/*.sh` locally and fix the findings. Keep behaviour identical: these
   scripts are referenced step by step in `docs/06-runbooks/`, so their output text must not
   change.
2. Where a warning is intentional, silence it on that line with
   `# shellcheck disable=SCxxxx` and a short reason.
3. Add a `shellcheck` job to `.github/workflows/ci.yml` (shellcheck is preinstalled on
   `ubuntu-latest`).

## Done when

- [ ] `shellcheck scripts/*.sh` exits 0.
- [ ] CI runs it on every PR.
- [ ] Each disabled warning has a reason comment.

## Safety note

`harden-host.sh` changes SSH and firewall settings on a real server. If a fix there is more
than quoting or style, split it into its own PR and say how you tested it.
