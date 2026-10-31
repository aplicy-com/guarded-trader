# build: add `make docs-assets` to regenerate the README images

Labels: good first issue,enhancement

## Context

`docs/assets/README.md` lists four manual steps to regenerate the README images with
`scripts/docs_assets/`: start the stack, produce the Telegram transcript, render, stop the
stack.

## What to do

1. Add a `docs-assets` Make target that runs steps 2 and 3 into a temporary directory. It
   should **fail with a clear message** if the dry-run stack isn't up on 127.0.0.1:8000,
   instead of starting it itself.
2. Replace steps 2 and 3 in `docs/assets/README.md` with the new target, and keep the
   expected output line.
3. Read Playwright's browser path from the existing `CHROME` environment variable, as
   `render.py` already does. Don't hard-code a path.

## Done when

- [ ] With the stack up, `make docs-assets` rewrites the four PNGs.
- [ ] With the stack down, it exits non-zero and says to run `make up`.
- [ ] The transcript JSON still contains `<chat-id>` and no other chat identifier.
