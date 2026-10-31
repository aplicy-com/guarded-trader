# Good first issue drafts

Drafts for the public launch, filed on 2026-10-31 as issues #3 to #10. The issues are now
the record: edit them on GitHub, not here, and don't run the loop below again (it would file
duplicates). It is kept to show how they were filed:

```bash
cd docs/issues-drafts
for f in 0*.md; do
  title=$(sed -n '1s/^# //p' "$f")
  labels=$(sed -n '3s/^Labels: //p' "$f")
  tail -n +5 "$f" > /tmp/issue-body.md
  gh issue create -R aplicy-com/guarded-trader --title "$title" --label "$labels" --body-file /tmp/issue-body.md
done
```

| Issue · draft | Title | Labels |
|---|---|---|
| [#3](https://github.com/aplicy-com/guarded-trader/issues/3) · [01](01-nfr8-pr-checklist.md) | docs: point NFR8's verification at the PR template | good first issue, documentation |
| [#4](https://github.com/aplicy-com/guarded-trader/issues/4) · [02](02-make-test-lint.md) | build: add `make test` and `make lint` that run both services | good first issue, enhancement |
| [#5](https://github.com/aplicy-com/guarded-trader/issues/5) · [03](03-pre-commit-ruff.md) | chore: add ruff hooks to pre-commit | good first issue, enhancement |
| [#6](https://github.com/aplicy-com/guarded-trader/issues/6) · [04](04-dependabot.md) | ci: add Dependabot for GitHub Actions and Python dependencies | good first issue, enhancement |
| [#7](https://github.com/aplicy-com/guarded-trader/issues/7) · [05](05-shellcheck.md) | ci: run shellcheck on scripts/*.sh | good first issue, enhancement |
| [#8](https://github.com/aplicy-com/guarded-trader/issues/8) · [06](06-link-check.md) | ci: check Markdown links in docs | good first issue, enhancement |
| [#9](https://github.com/aplicy-com/guarded-trader/issues/9) · [07](07-chart-theme-change.md) | fix(dashboard): re-colour the equity chart when the OS theme changes | good first issue, bug |
| [#10](https://github.com/aplicy-com/guarded-trader/issues/10) · [08](08-make-assets.md) | build: add `make docs-assets` to regenerate the README images | good first issue, enhancement |

This folder can be deleted at any time; nothing links to the drafts.
