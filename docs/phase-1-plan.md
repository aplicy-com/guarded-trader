# Phase 1 — Repo & Docs Scaffold

**Repo:** `<repo-dir>` · **Owner:** the operator (personal; transfer to Aplicy GitHub on success)
**Goal:** Every decision, risk and rule written down before a line of trading code exists. Docs-first, open-source-ready from day one.
**Out of scope:** any code that talks to Kraken.

## 1. Target layout

```
ai-trading-agent/
├── README.md                     # what/why/status, quick links, disclaimer
├── LICENSE                       # Apache-2.0, copyright the original author (easy to reassign later)
├── CLAUDE.md                     # project rules for Claude Code (below)
├── .gitignore  .env.example  .editorconfig
├── docs/
│   ├── 00-vision.md              # one page: thesis, non-goals, success criteria
│   ├── research/                 # 01-research-review.md already here
│   ├── 02-requirements.md        # the 4 capital rules as testable requirements (R1–R4) + NFRs
│   ├── 03-risk-register.md       # ID, risk, likelihood, impact, mitigation, owner, status
│   ├── 04-architecture/
│   │   ├── overview.md           # context + container diagrams (Mermaid)
│   │   ├── conductor.md          # research loop, ledger, gates, kill switch, Telegram
│   │   ├── execution-freqtrade.md# how Freqtrade is configured/wrapped, dry-run vs live
│   │   ├── data-flow.md          # sequence diagrams: nightly loop, live tick, halt
│   │   └── security.md           # key scopes, secrets, network, Tailscale plan
│   ├── 05-adr/                   # 0001-freqtrade, 0002-kraken, 0003-llm-never-orders,
│   │                             # 0004-mac-first-minipc-later, 0005-low-frequency-only,
│   │                             # 0006-apache-2-licence
│   ├── 06-runbooks/              # start-stop, kill-switch, nuclear-protocol, profit-sweep,
│   │                             # key-rotation, migrate-to-minipc
│   ├── 07-roadmap.md             # phases 1–5 with entry/exit gates
│   └── 08-paper-exit-criteria.md # what "3 weeks of paper passed" means, numerically
├── services/
│   ├── conductor/README.md       # placeholder, Phase 3
│   └── freqtrade/README.md       # placeholder, Phase 2 (user_data lives here)
└── infra/README.md               # docker-compose lands here in Phase 2
```

## 2. CLAUDE.md rules (summary)
- The LLM never places, modifies or cancels orders. Only the deterministic risk engine does.
- Secrets never enter the repo; `.env.example` only.
- Feature branches off `main`, conventional commits, no AI attribution trailers.
- Every architectural change gets an ADR; every operational procedure gets a runbook.
- Plans are written and approved before implementation in every phase.
- Python 3.12+, latest stable libs, clean architecture, tests for anything that touches money.

## 3. Paper exit criteria (draft — to refine in doc 08)
- ≥ 3 weeks continuous dry-run, ≥ 20 closed trades
- Net P&L after fees > 0; max drawdown < 10%; fee ratio (fees / gross profit) < 40%
- Zero risk-engine violations, zero unhandled halts
- Every LLM proposal in the period is logged and replayable

## 4. Claude Code prompt (paste as first message after `cd <repo-dir>`)

```
Read docs/research/01-research-review.md fully before doing anything.

Scaffold this repository as a docs-first, open-source-ready project for an
AI-assisted crypto trading system. Create the exact layout in
docs/phase-1-plan.md section 1. Rules:

- Write real content, not lorem ipsum. Derive every decision from the research
  review; where the review is silent, mark the line "TBD (Phase N)".
- docs/02-requirements.md: express these as testable requirements —
  R1 one-time $100 principal, never topped up; R2 trading capital = principal +
  working profit only; R3 profit above the daily cap is swept to an account the
  system has no key for; R4 hard loss limits (daily, drawdown, consecutive-loss)
  that halt trading and require human re-enable.
- docs/03-risk-register.md: at least 20 risks across market, execution, LLM,
  security, operational, legal/tax (Canada) — each with mitigation and owner.
- ADRs in MADR format, status Accepted, one per file.
- Runbooks are step-by-step and assume the reader is half-asleep at 2am.
- Mermaid for all diagrams.
- CLAUDE.md contains the rules in docs/phase-1-plan.md section 2, expanded.
- LICENSE: Apache-2.0, copyright 2026 the original author.
- git init, branch main, single conventional commit: "docs: scaffold
  docs-first project structure and initial decision records". No AI trailers.

Do not write any code that connects to an exchange. When done, list every file
created with a one-line summary and any TBDs you left.
```

## 5. Review checklist for the operator after the run
- [ ] R1–R4 read the way you meant them
- [ ] Risk register has nothing you disagree with
- [ ] Paper exit criteria are numbers you'd actually hold yourself to
- [ ] Nothing exchange-related exists yet
