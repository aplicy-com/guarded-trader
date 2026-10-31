# Good first issue drafts

Drafts for the public launch, not yet filed. Each one is small, needs no exchange account and
no money, and stays away from the trading path. To file one (labels exist by default in a new
GitHub repo):

```bash
cd docs/issues-drafts
for f in 0*.md; do
  title=$(sed -n '1s/^# //p' "$f")
  labels=$(sed -n '3s/^Labels: //p' "$f")
  tail -n +5 "$f" > /tmp/issue-body.md
  gh issue create -R aplicy-com/guarded-trader --title "$title" --label "$labels" --body-file /tmp/issue-body.md
done
```

| # | Title | Labels |
|---|---|---|
| [01](01-nfr8-pr-checklist.md) | docs: point NFR8's verification at the PR template | good first issue, documentation |
| [02](02-make-test-lint.md) | build: add `make test` and `make lint` that run both services | good first issue, enhancement |
| [03](03-pre-commit-ruff.md) | chore: add ruff hooks to pre-commit | good first issue, enhancement |
| [04](04-dependabot.md) | ci: add Dependabot for GitHub Actions and Python dependencies | good first issue, enhancement |
| [05](05-shellcheck.md) | ci: run shellcheck on scripts/*.sh | good first issue, enhancement |
| [06](06-link-check.md) | ci: check Markdown links in docs | good first issue, enhancement |
| [07](07-chart-theme-change.md) | fix(dashboard): re-colour the equity chart when the OS theme changes | good first issue, bug |
| [08](08-make-assets.md) | build: add `make docs-assets` to regenerate the README images | good first issue, enhancement |

Delete this folder once the issues are filed; the issues become the record.
