# History rewrite, 2026-10-31

Before the first public push, this repository's history was rewritten once with
`git filter-repo` ([ADR-0023](05-adr/0023-copyright-to-aplicy-and-public-release.md)). What
changed:
- server addresses (the VPS IPv4, Tailscale addresses) became documentation placeholders;
- personal names in file contents became "the operator" / "the original author";
- every commit's author and committer became the operator's GitHub no-reply identity;
- `Co-Authored-By` trailers were removed.

What did not change: file contents otherwise, commit order, and every author and commit date.
So "committed before it was run" claims can still be checked from the dates.

Every commit hash changed. Hashes cited in these docs were updated:

| Cited in | Pre-rewrite hash | Hash in this repository |
|---|---|---|
| `research/05-first-candidates.md` (pre-registration commit) | `beaece1` | `622c904` |
| `research/03-baseline-backtest.md` | `47bd5d7` | `89d82cc` |
| `research/06-ndax-feasibility.md` (NDAX fee overlay) | `574ab4c` | `fa8294e` |
| `research/06-ndax-feasibility.md` (its revert) | `3038b97` | `044f09b` |

The trial registry is not affected. It identifies trials by `strategy_hash`, a hash of the
strategy's source, parameters, fee, data snapshot and Freqtrade version, not by a git commit.
