# Phase 2 — Infra + Freqtrade Dry-Run

**Goal:** Freqtrade running in Docker on the Mac, dry-run, against live Kraken market data, with one hand-written low-frequency strategy — proving the execution path before Conductor exists.
**Out of scope:** Conductor, Claude API, real money, API keys with trade permission.

## 0. Key insight — residency is NOT blocking this phase
Dry-run uses public market data only. No API key is needed until live. So Phase 2 proceeds while the Kraken support ticket is open; the roadmap entry gate is amended to require residency only before **key creation** (step 2E), not phase start.

## 1. Decisions to lock (my recommendations)

| Item | Recommendation | Why |
|---|---|---|
| Quote currency | **USD** | Deepest Kraken liquidity, most pairs, community strategies default to it. CAD pairs are thin. Fund CAD via Interac, convert once. |
| Pair universe | BTC/USD, ETH/USD, SOL/USD + 3–5 top-liquidity majors, **excluding every asset already held** (ADA, DOT, KAVA, SC, ACA, XTZ) | R5 isolation; liquidity; ≤3 positions anyway |
| Timeframe | 4h primary, 1d confirmation | D4 low-frequency |
| Data source | Freqtrade `download-data` from Kraken (free), 2+ years | Sufficient at 4h; paid data is Phase 5 if ever |
| Ledger DB | SQLite (WAL), single writer = Conductor | One less container; scale is tiny. Reversible via ADR. |
| Secret scanning | gitleaks pre-commit hook | Standard, fast |
| Mac sleep | Amphetamine, always-on session at login, kept awake with lid closed (superseded the draft `caffeinate` idea — see `infra/README.md`) | Until mini-PC |
| Remote access | Install Tailscale now on Mac + phone | Zero effort, tests the remote story early |
| Protections (draft) | StoplossGuard 3 stops/24h → 12h lock; MaxDrawdown 10% → halt; CooldownPeriod 2 candles; LowProfitPairs off in paper | Mirrors R4; tuned in Phase 3 |

## 2. Work packages (each = one Claude Code session, one branch, one PR)

**2A — Infra skeleton** (`feat/infra-freqtrade`)
`infra/docker-compose.yml` with Freqtrade only; `services/freqtrade/user_data/` with `config.dry_run.json` (dry_run true, dry_run_wallet 100, stake USD, max_open_trades 3, protections from §1); `.env.example` updated; `infra/README.md` = how to start/stop; gitleaks hook; Makefile targets `up`, `down`, `logs`, `download-data`, `backtest`.

**2B — Market facts** (`chore/kraken-market-facts`)
Script `scripts/kraken_market_facts.py` using ccxt **public** endpoints: for each candidate pair pull min order size, price/amount precision, and 30-day volume; write `docs/research/02-kraken-market-facts.md`. Resolves TBDs: min sizes, pair universe, confirms none violate $100 sizing (stake ≈ $30/position must exceed every min).

**2C — Data + baseline strategy** (`feat/baseline-strategy`)
Download 2y of 4h+1d OHLCV. Write `Baseline4h.py`: simple trend-following (e.g. EMA cross with ATR stop, ≤4 params), documented. Backtest with fees 0.26% + 0.1% slippage buffer. Record results in `docs/research/03-baseline-backtest.md` — including if it loses. Purpose is path validation, not alpha.

**2D — Dry-run live** (`feat/dry-run`)
Start Freqtrade dry-run against live Kraken data with Baseline4h. Freqtrade's own Telegram bot enabled (status only) so you can watch from your phone. Runs continuously from here — this is also the burn-in for the Mac-as-host assumption.

**2E — Key + residency (blocked on Kraken support)**
Once residency shows Canada: create API key (Query + Trade, no Withdraw, IP-whitelist), store in LastPass + `.env`, verify permissions per key-rotation runbook. **Still dry-run.** Update roadmap gate.

**2F — Docs closure** (`docs/phase-2-close`)
Resolve every Phase-2 TBD in place; ADR-0008 (USD quote), ADR-0009 (SQLite ledger); accountant question list for Vajira (tax classification, deemed-acquisition of 2021 holdings) in `docs/09-tax-questions.md`.

## 3. Exit gate (from roadmap, sharpened)
- Freqtrade dry-run uptime ≥ 7 consecutive days on the Mac
- Baseline4h backtest documented with realistic costs
- Market-facts doc confirms every whitelisted pair tradeable at $30 stake
- Key created with verified scopes (if residency resolved; else explicitly deferred)
- No Phase-2 TBDs remain

## 4. Model guidance for Claude Code
Sonnet for 2A/2B/2F. Opus for 2C (strategy + backtest interpretation). Plan mode first on every package.

## 5. Your review points
1. USD vs CAD quote — agree?
2. SQLite instead of Postgres — agree?
3. Exclusion list of held assets correct and complete?
4. 7-day dry-run uptime as the exit bar — realistic for your Mac?
