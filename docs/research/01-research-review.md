# Research Review — Frameworks, LLM-Agent Results, Risk Controls

**Project:** AI Trader (working name) · **Date:** 2026-09-09 · **Status:** Input to Phase 1 (docs scaffold)
**Scope:** What to build on, what the evidence says about LLMs trading, and which risk controls are non-negotiable. Sources at the end.

---

## 1. Executive summary

1. **Do not let the LLM trade tick-by-tick.** Every public live-money experiment with frontier LLMs as the decision-maker (Nof1 Alpha Arena, Seasons 1 and 1.5) lost money in aggregate: the pooled portfolio lost about a third of its capital and only 6 of 32 model-runs finished profitable. Failure modes were consistent: over-trading, fee drag, bad position sizing, mistimed entries. Nof1's own founder: LLMs can't make money by themselves; they need a sophisticated harness.
2. **Academic "LLM beats buy-and-hold" results don't survive leakage control.** A 2026 memory-controlled benchmark (KTD-Fin) found LLM agents' returns were largely explained by passive market/style exposure, with little persistent stock-selection alpha.
3. **Therefore the architecture is: deterministic execution + risk core, LLM as researcher/reviewer in a nightly loop with promotion gates.** This is also the pattern the surviving retail systems use: simple rules, low turnover, strict risk limits, mature execution infrastructure.
4. **Framework decision: Freqtrade as the execution/risk engine, our own "Conductor" layer on top.** NautilusTrader is technically superior but mid-transition to v2 (final 1.x release Aug 2026; tutorials still v1) — wrong moment to adopt. qanat is a research DAG tool, not an execution engine. Hummingbot is a market-making framework, not suited to $100 signal trading.
5. **$100 changes strategy class, not just size.** A Kraken taker round-trip costs ~0.5%; any edge under ~0.7%/trade is fee noise. We trade low-frequency (4h/1d bars), maker orders where possible, 1–3 positions max.

---

## 2. Framework comparison

| | Freqtrade | NautilusTrader | Hummingbot | qanat | vectorbt |
|---|---|---|---|---|---|
| Role | Signal-driven bot: backtest → dry-run → live | Event-driven engine, research-to-live parity | Market making / arbitrage | Alpha research as DAGs (weights tables) | Vectorised backtesting library |
| Language | Python | Rust core, Python API | Python (+Gateway) | Python/SQL, DuckDB | Python |
| Kraken support | Yes via CCXT (spot) | Native Rust adapter (spot + futures) | Yes | N/A (sources are yours) | N/A |
| Paper trading | Built-in dry-run mode (same code path as live) | Sandbox adapter | Paper scripts | No | No |
| Risk controls built in | StoplossGuard, MaxDrawdown, CooldownPeriod, LowProfitPairs, stake limits | Risk engine with order rate/size limits | Basic | None | None |
| Optimisation | Hyperopt, FreqAI (ML) | Bring your own | — | — | Fast param sweeps |
| Ops | Docker, Telegram, REST API, web UI | Docker, Redis, message bus | Docker, CLI, MCP server | CLI + console | Library |
| Maturity | Since 2017, 25k+ stars, monthly releases | Very mature core; **v1→v2 cutover in progress (Aug–Sep 2026)** | Mature; $34B+ reported volume | Young (~60 stars) | Mature library |
| Licence | GPL-3 | LGPL-3 (CLA for contributions) | Apache-2.0 | check repo | Apache-2.0 (open version) |
| Fit for us | **Primary execution + risk engine** | Revisit after v2 stabilises | No | Optional research sandbox | Research utilities |

**Why Freqtrade wins now:** dry-run mode is exactly our 3-week paper gate with zero code change; strategies are Python classes, which is what an LLM can generate, test and diff; protections give us a second, independent risk layer beneath our own; Telegram + REST give us remote control from the start. GPL-3 is fine because we run it as a separate service (Docker) and talk to it over its REST API; our repo stays under our own licence.

**Kraken specifics to verify in Phase 2:** per-pair minimum order sizes (some pairs' minimums approach $5–10 notional), rate limits, and maker/taker tiers (~0.16%/0.26% at low volume on Kraken Pro).

---

## 3. What the LLM-agent evidence says

| Source | Setup | Result | Lesson for us |
|---|---|---|---|
| Nof1 Alpha Arena S1 (Oct–Nov 2025) | 6 LLMs, $10k each, live crypto perps | 4 of 6 lost; GPT-5 −63%; winner Qwen3 +22% | Early PnL dominated by fees from over-trading and "quick tiny gains". Winner traded far less. |
| Alpha Arena S1.5 (2026) | 8 models × 4 contests, US tech stocks, leverage | Pool lost ~⅓; 6 of 32 runs profitable; range +34.6% to −96% | Same prompt → radically different decisions. Non-determinism is a risk-control problem. |
| Agent Market Arena (WWW 2026) | Live multi-market benchmark, 4 agent archetypes × 5 LLMs | Framework paper; results vary by agent design more than by model | Agent scaffolding matters more than model choice. |
| FinMem / FinCon / TradingAgents (2023–25) | Layered memory, multi-agent debate; backtests on US equities | Strong Sharpe vs buy-and-hold in-sample | Useful design ideas (memory, reflection, role separation) — but see next row. |
| KTD-Fin (May 2026) | Leakage-controlled, 10 frontier LLMs, CSI300 2024–26 | Returns mostly passive beta/style; limited alpha | Treat LLM "alpha" claims as unproven. Measure our returns net of market exposure. |
| "Agentic Trading" survey (May 2026) | Literature review | Calls out deterministic replay / audit as unsolved | We log every LLM input/output and make the execution path replayable. |

**Design consequences**
- LLM produces *candidate strategies, parameters, reviews and post-mortems* — never orders.
- Every LLM proposal passes deterministic gates (backtest → walk-forward → paper) before allocation.
- Turnover is capped by the risk engine regardless of what any strategy wants.
- Full prompt/response logging with hashes; strategy versions pinned in git.

---

## 4. Risk-control practice (what survivors actually do)

Drawn from the FIA automated-trading risk-controls whitepaper, retail practitioner post-mortems, and Freqtrade's protections.

| Control | Setting for $100 pilot | Layer |
|---|---|---|
| Capital ceiling | Hard `max_deployed_capital` = principal + working profit | Conductor + Freqtrade `stake_amount` |
| Per-trade risk | 1–2% of equity at risk; ATR-based sizing | Strategy + risk engine |
| Position count | Max 2–3 open, correlation guard (BTC/ETH count as one) | Freqtrade `max_open_trades` + our check |
| Stop-loss | Mandatory per trade; trailing where strategy allows | Freqtrade |
| Daily loss limit | e.g. −3% → halt new entries until next UTC day | Freqtrade StoplossGuard + Conductor |
| Max drawdown | e.g. −10% from peak → flatten + halt + require human re-enable | Freqtrade MaxDrawdown + Conductor |
| Consecutive-loss breaker | N losses in a row → cooldown | Freqtrade CooldownPeriod |
| Turnover cap | Max trades/day per strategy | Risk engine |
| Kill switch | Blocks all *new* orders, persists across restarts; separate **flatten** command; both reachable via Telegram | Conductor |
| "Nuclear" protocol | On data loss/exchange outage/anomaly: cancel open orders, flatten if possible, halt, log state, alert | Conductor runbook |
| Profit sweep | Nightly: profit above daily cap → separate Kraken sub-account / wallet the bot has no key for | Ledger job |
| Key hygiene | API key: query + trade only, **no withdrawal**, IP-whitelisted; secrets in env/LastPass, never in repo | Ops |
| Overfitting defence | ≤6 tunable params per strategy; walk-forward (anchored + rolling); conservative fees/slippage in backtests; re-validate every 4–6 weeks; reject if OOS Sharpe < 50% of IS | Research loop |
| Observability | Equity curve, exposure, fee ratio, turnover, halt state; alert on silence (heartbeat) | Grafana/Telegram |

Reference case for why kill switches exist: Knight Capital lost $440M in 45 minutes from a deployment error.

---

## 5. "Success stories" — honest read

- **No verified public case of an autonomous LLM agent compounding real money over months.** Claims exist; audited track records don't. We should expect to be a data point, not a beneficiary.
- **What has demonstrably worked at scale:** deterministic, well-instrumented execution (Hummingbot's market-making volume; Freqtrade's long-running community strategies such as NostalgiaForInfinity), where the "AI" is at most an optimiser (Hyperopt/FreqAI) and never the order router.
- **Common traits of surviving retail systems:** few parameters, low turnover, realistic cost modelling, long paper period, independent risk layer, regular re-validation, and boring infrastructure (Docker, Telegram, Postgres).
- **Adoptable ideas from the research agents:** layered memory of past trades and market regimes (FinMem), role separation — analyst / risk reviewer / critic (TradingAgents, FinCon), and structured reflection on losses. We adopt these *in the nightly research loop*, not the live path.

---

## 6. Decisions this review locks in

| # | Decision |
|---|---|
| D1 | Execution + base risk engine: **Freqtrade** in Docker, Kraken via CCXT, dry-run for paper |
| D2 | Our own **Conductor** service (Python, FastAPI): Claude-driven research loop, ledger, profit sweep, promotion gates, kill switch, Telegram |
| D3 | LLM never places orders; all proposals pass backtest → walk-forward → 3-week paper → 25% allocation → 100% |
| D4 | Low-frequency strategies only (4h/1d), maker-preferred, ≤3 positions |
| D5 | Re-evaluate NautilusTrader once v2 has had 2–3 stable releases |
| D6 | qanat/vectorbt optional in the research sandbox; not on the critical path |

---

## 7. Open questions for Phase 2

1. Exact Kraken min order sizes and fee tier for CAD vs USD pairs — pick quote currency.
2. Whether the nightly research loop runs on the Mac (needs to be awake) or on the mini-PC from day one. *(Resolved 2026-10-04: neither — a Hetzner VPS, ADR-0011.)*
3. Data source for backtests: Kraken OHLCV via Freqtrade `download-data` (free) vs a paid provider.
4. Model budget per night for research runs.

---

## Sources

- github.com/fidetolabs/qanat — README
- coincodecap.com/open-source-trading-bots-on-github (Apr 2026 review)
- alexbobes.com/crypto/best-freqtrade-alternatives; gainium.io/compare/freqtrade-vs-hummingbot
- nautilustrader.io/kraken; github.com/nautechsystems/nautilus_trader/releases/tag/v1.231.0
- business-standard.com — "AI bots auditioning for Wall Street trading are mostly losing money" (May 2026)
- protos.com; forklog.com; iweaver.ai — Alpha Arena Season 1 coverage (Nov 2025 / Aug 2026)
- arxiv.org/abs/2510.11695 — Agent Market Arena (WWW 2026)
- arxiv.org/abs/2605.28359 — KTD-Fin, memory-controlled LLM trading benchmark (May 2026)
- arxiv.org/abs/2605.19337 — Agentic Trading survey (May 2026)
- arxiv.org/abs/2311.13743 — FinMem
- fia.org — Best Practices for Automated Trading Risk Controls (2024)
- petrvojacek.cz — Trading Bot in Practice: Overfitting, Risk Management (Mar 2026)
- koinly.io / cryptoslate.com — Canadian exchange registration status (2026)
