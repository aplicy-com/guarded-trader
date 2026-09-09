# 03 — Risk Register

Living document. Reviewed at every phase gate (`07-roadmap.md`) and after
any incident. **Likelihood** and **Impact** are rated Low/Medium/High at
the $100-principal, Phase 1–4 scale — re-rate if principal or scope ever
changes. **Owner** is a role, currently all held by the operator,
except where the automated system is the enforcing owner.

Status legend: **Open** — mitigation planned/partial, not yet verified.
**Mitigated** — control designed and specified here; implementation lands
in the phase noted. **Accepted** — residual risk knowingly carried.

## Market risk

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| M1 | Sudden adverse price move (flash crash, news shock) exceeds the stop-loss's assumed slippage, causing a fill far worse than modelled. | Medium | High | ATR-based stop sizing (not fixed %); max-drawdown hard halt (R4); avoid illiquid/low-cap pairs; documented in `06-runbooks/nuclear-protocol.md` for the "exchange anomaly" case. | Risk engine (Freqtrade) / Conductor | Mitigated (design) — implemented Phase 2 |
| M2 | Low liquidity in a traded pair causes slippage well beyond backtest assumptions. | Medium | Medium | Restrict to BTC/ETH and other high-24h-volume majors only (low-frequency ADR-0005); minimum volume filter in pair whitelist. | Strategy design | Mitigated (design) |
| M3 | Correlation risk — BTC and ETH (and most alts) move together, so nominal "2–3 positions" can be one effective bet. | High | Medium | Correlation guard treats BTC/ETH (and any pair with rolling correlation above a threshold — TBD (Phase 3) exact threshold) as a single exposure unit for position-count and risk-budget purposes. | Conductor | Mitigated (design) |
| M4 | At $100, exchange fees erode any edge smaller than the round-trip cost (~0.5% taker on Kraken). | High | High | Maker-preferred order placement; strategies must model conservative fees/slippage in backtest; minimum expected edge threshold (~0.7%/trade) before a strategy is considered; low-turnover-only strategies (research review §5). | Strategy design / Research loop | Mitigated (design) |
| M5 | Regime change — a strategy validated in one market regime (e.g. trending) fails when conditions shift (e.g. chop, high-vol bear). | High | Medium | Anchored + rolling walk-forward validation before promotion; scheduled re-validation every 4–6 weeks; reject/demote on OOS Sharpe collapse (NFR5). | Research loop | Mitigated (design) — implemented Phase 3 |
| M6 | Stablecoin or quote-asset de-peg / failure affects the value or liquidity of held balances. | Low | High | Prefer well-established quote assets; principal is small enough ($100) that total loss is bounded; monitor exchange notices. | Operator | Accepted |
| M7 | Pre-existing personal holdings in the same Kraken account (bought before the project, gifted, or otherwise not system-acquired) get sized into `max_deployed_capital` as if they were working profit, or get sold by a strategy that has no way of knowing they weren't the bot's to trade. | Medium | High | R5 (account isolation): capital sizing counts only ledger-recorded, system-bought balances; startup check aborts and alerts if a whitelisted pair holds an unexplained balance, rather than silently absorbing or trading it. | Conductor | Mitigated (design) — implemented Phase 2 |

## Execution risk

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| E1 | A Freqtrade, CCXT, or Kraken API change breaks order placement or introduces a silent bug. | Medium | High | Pin dependency versions; dry-run parity means the same code path is exercised daily before it ever matters; monitor Freqtrade/CCXT release notes before upgrading; canary any upgrade in dry-run first. | Ops | Mitigated (design) — implemented Phase 2 |
| E2 | Exchange outage or API downtime occurs while a position is open. | Medium | High | Nuclear protocol runbook (cancel/flatten where possible, halt, alert); no leveraged/margin positions in Phase 1–4 so a stuck position cannot itself trigger a margin call. | Ops / Conductor | Mitigated (design) |
| E3 | Freqtrade's local order/position state desyncs from the exchange's actual state (e.g. partial fill, missed webhook). | Medium | Medium | Reconcile positions against exchange state on every process start; alert on any mismatch rather than silently trusting local state. | Conductor | Mitigated (design) — implemented Phase 2/3 |
| E4 | A bad deploy or config error causes a runaway order loop (Knight Capital reference case: $440M lost in 45 minutes). | Low | High | Hard turnover cap enforced by the risk engine regardless of strategy signals; kill switch tested before every deploy; short canary/observation window after any deploy before leaving it unattended. | Ops | Mitigated (design) |
| E5 | Host clock drift causes exchange request-signature failures or misaligned backtest/live bar timing. | Low | Low | NTP time sync enabled on the host; monitored as part of the heartbeat/observability stack. | Ops | Mitigated (design) — implemented Phase 2 |
| E6 | Freqtrade minimum order size (notional) for a given pair is not met by the position size the risk budget allows at $100 principal. | Medium | Medium | Verify Kraken per-pair minimums during Phase 2 setup; size positions and choose pairs accordingly; documented as an open question in research review §7.1. | Ops | Open — TBD (Phase 2) |

## LLM / research-loop risk

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| L1 | LLM proposes a strategy with a logic bug (e.g. inverted signal, off-by-one on bar timing). | High | Medium | No LLM-authored strategy reaches capital without passing deterministic backtest, walk-forward, and unit tests first; a second LLM review pass is used as an additional (not sole) check. | Research loop / Operator | Mitigated (design) — implemented Phase 3 |
| L2 | LLM proposes an overfit strategy (curve-fit to historical backtest data). | High | High | ≤6 tunable parameters cap; anchored + rolling walk-forward; reject if OOS Sharpe < 50% of IS Sharpe (NFR5). | Research loop | Mitigated (design) |
| L3 | Non-determinism — the same prompt produces materially different strategy code/parameters run to run (observed directly in Alpha Arena S1.5). | High | Medium | Once a strategy is promoted, its code is pinned to a git commit hash and never silently re-generated; the live path never re-prompts the LLM mid-trade; every prompt/response is logged with a hash (NFR1). | Conductor | Mitigated (design) |
| L4 | Prompt injection via external data fed into the research loop (news headlines, on-chain data, social sentiment) attempts to alter the loop's behaviour or safety checks. | Medium | Medium | All fetched external content is treated as untrusted data, never as instructions, when composing prompts; safety/promotion-gate logic lives outside the LLM's control entirely (deterministic code, not a prompt instruction). | Conductor | Mitigated (design) — implemented Phase 3 |
| L5 | LLM API cost overrun from an unbounded or malfunctioning nightly research loop. | Medium | Low | Nightly token/spend budget with a hard cutoff; alert on overrun; exact budget TBD (Phase 3, research review §7.4). | Ops | Open — TBD (Phase 3) |
| L6 | LLM vendor outage or rate-limiting blocks a night's research loop. | Medium | Low | Research loop failure is non-blocking for live trading — the live path is 100% deterministic Freqtrade and does not depend on the LLM being reachable; loop retries the next scheduled run. | Conductor | Mitigated (design) |
| L7 | The nightly research loop's cumulative LLM API cost, over time, exceeds the $100 principal the system manages — the compute cost of running the experiment becomes larger than the capital at risk. | Medium | Low | R6 (research-loop cost ceiling): monthly budget with an 80% alert and a 100% hard stop; the hard stop pauses only the research loop, never trading (ADR-0003). Cost is tracked and reported honestly alongside trading results (`00-vision.md`), so this stays a visible trade-off rather than a hidden one. | Operator | Mitigated (design) — implemented Phase 3 |

## Security risk

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| S1 | Exchange API key or other secret leaks via the repo, logs, or a shared screen. | Medium | High | Secrets only in env vars / 1Password, never committed; `.gitignore` covers `.env` and key files; pre-commit secret scanning (tool TBD Phase 2); repo reviewed before any public push. | Operator | Mitigated (design) — implemented Phase 2 |
| S2 | Exchange API key is over-scoped (has withdrawal permission) by mistake. | Low | High | Key created with query + trade only, withdrawal explicitly disabled, IP-whitelisted; scope verified at creation and at every rotation (`06-runbooks/key-rotation.md`). | Operator | Mitigated (design) |
| S3 | Host (Mac, later mini-PC) is compromised via malware or an unpatched vulnerability. | Low | High | OS auto-updates enabled; no unnecessary exposed ports; remote access via Tailscale rather than public-facing ports (`04-architecture/security.md`); minimal installed software on the trading host. | Ops | Mitigated (design) — implemented Phase 2 |
| S4 | Telegram bot token leaks, allowing an unauthorized party to issue control commands (including, in the worst case, attempting to disable safety controls). | Low | High | Token stored as a secret, never committed; chat/user ID allowlist enforced in Conductor before executing any command; kill switch/flatten are the only destructive-adjacent commands and both only ever *reduce* risk, never increase it. | Conductor | Mitigated (design) — implemented Phase 3 |
| S5 | A dependency (PyPI package used by Freqtrade, Conductor, or CI) is compromised (supply-chain attack). | Low | Medium | Pinned versions with a lockfile; automated dependency-update alerts (Dependabot or equivalent); diffs reviewed before accepting an upgrade, especially for packages with exchange/network access. | Ops | Mitigated (design) — implemented Phase 2 |
| S6 | Local database (ledger, Freqtrade state) is not encrypted at rest and the host is lost or stolen. | Low | Medium | Full-disk encryption on the trading host (FileVault on Mac, LUKS on mini-PC); no secrets stored in the ledger DB itself (secrets live only in env/1Password). | Ops | Open — TBD (Phase 2) |

## Operational risk

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| O1 | Host goes to sleep, loses power, or the process crashes, silently stopping monitoring and/or leaving positions unmanaged. | Medium | High | Heartbeat monitoring with alert-on-silence (NFR4); sleep/power-nap disabled on the Mac host (`caffeinate` or equivalent) during Phase 1–4; UPS considered for the mini-PC migration (Phase 4, `06-runbooks/migrate-to-minipc.md`). | Ops | Mitigated (design) — implemented Phase 2/3 |
| O2 | The nightly research loop and live trading process contend for host resources (CPU/memory), degrading live execution timing. | Low | Medium | Research loop and execution engine run as separate containers/processes with resource limits; research loop scheduled for low-activity hours. | Conductor | Mitigated (design) — implemented Phase 3 |
| O3 | A halt fires at 2am and no human is available to respond quickly. | High | Low | Halts are safe-by-default — they stop new risk-taking (or flatten), they never *increase* exposure by doing nothing; runbooks are written for a half-asleep reader with no time pressure implied; Telegram alert is informational, not an emergency page. | Operator | Accepted (by design) |
| O4 | Ledger database or configuration is lost (disk failure, accidental deletion). | Low | Medium | Nightly automated DB backup (Phase 3+); configuration lives in git; secrets are recoverable independently from 1Password. | Ops | Open — TBD (Phase 3) |
| O5 | Version drift between the backtest/dry-run environment and the live environment produces different behaviour for "the same" strategy. | Low | Medium | Identical Docker image used for backtest, dry-run, and live; dependency versions pinned; promotion gate re-runs the exact pinned strategy version, never a re-generated copy. | Ops | Mitigated (design) — implemented Phase 2 |
| O6 | The operator is unavailable for an extended period (travel, illness) while the system is live. | Medium | Medium | System is safe unattended by design (R4 halts require re-enable, not constant supervision); a documented "pause everything" procedure exists for planned absences — TBD (Phase 4, extend `06-runbooks/start-stop.md`). | Operator | Open — TBD (Phase 4) |

## Legal / tax risk (Canada)

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| T1 | CRA classifies the trading activity as business income rather than capital gains (or vice-versa), materially changing tax treatment and filing obligations. | Medium | Medium | Consult an accountant before the first live trade with real profit; keep complete, contemporaneous records from day one regardless of eventual classification (NFR6). | Operator | Open — TBD (Phase 2), confirm classification before going live |
| T2 | Insufficient records (cost basis, disposition value in CAD at time of trade) to support a CRA filing. | Medium | Medium | Ledger records CAD-equivalent fair value, cost basis, and disposition for every fill from the first live trade; exportable report format defined before going live. | Conductor | Mitigated (design) — implemented Phase 3 |
| T3 | Kraken's regulatory/registration status in Canada changes, restricting access or requiring asset migration. | Low | Medium | Monitor Kraken's Canadian compliance status periodically; principal is small ($100) which bounds exposure to this risk; a documented exchange-migration path exists in principle — TBD (Phase 4) if/when needed. | Operator | Open — TBD (Phase 2), verify current registration status |
| T4 | Applicable GST/HST or other tax treatment on trading activity/fees is unclear. | Low | Low | Consult an accountant; not expected to be material at $100 principal, but the question should be settled before scaling, if the project ever scales. | Operator | Open — TBD (Phase 2) |
| T5 | Publishing this repository publicly inadvertently exposes personal financial details, account identifiers, or strategy details tied to real money. | Medium | Medium | Secrets excluded via `.gitignore`; no account numbers, balances, or personally identifying transaction data committed to tracked files; manual review before each push while the repo is public (`CLAUDE.md` §5). | Operator | Mitigated (design) |
| T6 | Losses are not properly documented/claimable due to poor record-keeping, forfeiting a legitimate tax offset. | Low | Low | Same ledger/export mechanism as T2 covers losses as well as gains; reviewed with the same accountant consultation. | Conductor | Mitigated (design) |

## TBD summary

Open items requiring resolution before the phase noted: E6 (Phase 2, min
order sizes), L5 (Phase 3, nightly LLM budget), S6 (Phase 2, disk
encryption), O4 (Phase 3, backup schedule), O6 (Phase 4, absence
procedure), T1/T3/T4 (Phase 2, accountant + registration-status check).
M7 is mitigated by design (R5) but its startup-abort clearance runbook is
still TBD (Phase 2) — see `docs/02-requirements.md` R5. L7 is mitigated
by design (R6) but its `monthly_llm_budget` value is still TBD (Phase 3)
— see `docs/02-requirements.md` R6, same open item as L5's nightly budget.
