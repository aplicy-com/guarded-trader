# NDAX as a replacement venue for Kraken: feasibility spike

Date: 2026-10-28 (UTC). Branch: `spike/ndax`. Public endpoints only; no API key, no `.env`, no
account. Probe scripts: [`scripts/spike_ndax/`](../../scripts/spike_ndax/README.md). Image:
`freqtradeorg/freqtrade:2026.8` (ccxt 4.5.76), the same pin as `infra/docker-compose.yml`.

## Bottom line

**NDAX works for market data and Freqtrade dry-run. It cannot replace Kraken for live trading
as the system is designed today**, for two reasons that are not cost:

1. **No stop-loss on exchange.** Freqtrade has no NDAX class. The generic class refuses
   `stoploss_on_exchange: true` (`ConfigurationError: On exchange stoploss is not supported for
   NDAX.`), and the live pilot config depends on it (ADR-0019). Stops would only exist while
   the bot is running.
2. **ccxt wants the account's login and password.** `ccxt.ndax` lists `login` and `password` as
   required credentials. Its credential check runs before every private call, even though the
   calls are signed with the API key. Putting the account password in the bot's environment is
   at least as dangerous as a withdrawal-capable key: CLAUDE.md §0 rule 2 territory. The
   official API docs don't say whether an API key can be scoped without withdrawal permission.
   Nothing here could be verified without an account. See [Credentials](#credentials-and-the-no-withdrawal-rule).

**Cost is NDAX's real advantage.** NDAX charges a flat 0.20 % per trade; Kraken Tier-1 taker is
0.80 %. NDAX's books are thin, though: the bid–ask spread on the whitelist pairs was
35–91 bps, so a market order pays roughly 0.20 % + ~0.29 % half-spread ≈ **0.49 % per side**.
Kraken's backtest model is 0.90 % per side. NDAX costs about half as much.

**At NDAX's fee, C05 and C04 turn profitable, but neither passes Gate 1.** C05 becomes the first
candidate to beat its random-entry null's Sharpe 95th percentile (97th percentile). It still
fails on the IS-Sharpe floor, trade concentration and force-exit share. At 2× the fee
(0.60 % per side, close to the spread-aware 0.49 %), C05 loses money again (−$21.58).
Most of the improvement comes from the fee level, and the measured spread takes much of it
back.

## What was checked, and the result

| Question | Answer | Evidence |
|---|---|---|
| ccxt `ndax` exists in the pinned image | ✅ ccxt 4.5.76 | `ndax in ccxt.exchanges` |
| Freqtrade support level | ⚠️ "known to ccxt, not officially supported"; generic `Exchange` class | Freqtrade startup log; `list-exchanges` |
| Markets load | ✅ 87 markets, 1.1 s | `load_markets()` |
| Quote currencies | ⚠️ **CAD only, in practice.** USD markets exist and ccxt marks them `active`, but their books are empty and 24 h volume is 0. BTC/USDT's last trade was at 29,869 with an empty book | probes 01, 02 |
| OHLCV 4h / 1d | ✅ Both work (1,000 candles per call). ⚠️ **Candles are labelled by close time**, not open time; ⚠️ 4h history starts 2022-03/04 | [Data quality](#data-quality) |
| Order book | ✅ Works for CAD pairs; spreads wide (below) | `fetch_order_book` |
| Minimum order sizes | ✅ Every whitelist pair's minimum is below C$1.50 notional. API reports no min cost (`None`), so an exchange-side notional minimum, if any, is unknown | table below |
| Fees from the API | ❌ `fetchTradingFees`/`fetchTradingFee` are not supported. ccxt hard-codes 0.20 % maker / **0.25 %** taker, which is not the official flat 0.20 % | `has` flags; ccxt `ndax.py` |
| Freqtrade dry-run | ✅ Runs: 6 CAD pairs, candles refreshed, incomplete candle dropped, strategy analysed, heartbeats, 0 errors | [Dry-run](#freqtrade-dry-run) |
| Stop-loss on exchange | ❌ Not available through Freqtrade (ccxt does have stop-market/stop-limit order types) | [Stop-loss](#stop-loss-on-exchange) |

### Official fee

Verified 2026-10-28 on NDAX's own page, <https://ndax.io/en/fees>:

> Ndax charges a flat 0.20% trading fee on every buy and sell order — the same rate at any trade
> size, with no volume tiers and no maker/taker split.
>
> You trade at the displayed order-book price, with the 0.20% commission charged on top and shown
> before you place the order.

"No maker/taker split" means limit orders save nothing on fees. The only lever left is the
spread. Kraken's model assumes every fill is a taker; on NDAX that distinction disappears.

### Minimum order sizes (CAD whitelist)

| Pair | Min amount | Min cost (API) | Amount step | Price tick | Min notional ≈ CAD |
|---|---|---|---|---|---|
| BTC/CAD | 0.00001 | none | 1e-08 | 0.01 | 1.14 |
| ETH/CAD | 0.0001 | none | 1e-06 | 0.01 | 0.33 |
| SOL/CAD | 0.01 | none | 1e-06 | 0.01 | 1.42 |
| XRP/CAD | 0.1 | none | 0.001 | 0.0001 | 0.19 |
| LINK/CAD | 0.01 | none | 0.0001 | 0.01 | 0.16 |
| LTC/CAD | 0.001 | none | 1e-05 | 0.01 | 0.08 |

All clear the pilot's ~C$26 stake and a ~C$45 per-position stake many times over.

### Liquidity and spread

Snapshot taken 2026-10-28 ~01:45 UTC: three samples per pair, 4 s apart, plus one earlier
sample. Overnight in North America, so this is one quiet moment, not a distribution.

| Pair | Spread (bps) | Est. slippage on a C$40 market order (bps vs mid) | 24 h volume (CAD) |
|---|---|---|---|
| BTC/CAD | 37–43 | 18 | 718,616 |
| ETH/CAD | 43–44 | 21 | 555,832 |
| SOL/CAD | 35–57 | 18 | 164,884 |
| XRP/CAD | 50–53 | 26 | 259,223 |
| LINK/CAD | 67–80 | 34 | 15,538 |
| LTC/CAD | 83–91 | 42 | 6,403 |

For comparison, Kraken's whitelist pairs trade $94 M–$5.5 B **per 30 days**
([02](02-kraken-market-facts.md)); NDAX's BTC/CAD trades about C$0.7 M **per day**. At $100
scale, depth is not the problem: a C$40 order fills inside the top level. The spread is. On
NDAX it costs as much as the fee or more on every pair; LINK and LTC cost about 2× the fee.
A cost model with Kraken's 0.10 % slippage buffer understates NDAX's real cost.

### Data quality

- **Close-time labels.** For 28 of 28 recent days, NDAX's 1d candle labelled `D` equals the
  six 4h candles that *end* at `D` (close-time labelling); 0 of 28 match open-time labelling.
  The newest candle is the in-progress one, stamped in the future (a 1d candle labelled
  2026-10-29 at 01:42 UTC on 2026-10-28). Freqtrade assumes open-time labels. In live and
  dry-run this is harmless: Freqtrade drops the in-progress candle and acts on completed data.
  In anything that joins NDAX candles with other data or timeframes, everything is off by one
  period: informative-pair merges add an extra period of lag, timerange boundaries shift by one
  candle, and comparisons against Kraken's archive misalign. The lag errs toward conservatism,
  not lookahead. **Downloaded candles must be shifted back one period at ingest**, and the
  leak checks (05's P0 follow-up) run on that path.
- **History depth.** 1d: from 2021-06-02 (SOL from 2021-12-26). 4h: from 2022-03-11 (LTC) and
  2022-04-04 (BTC, ETH). The canonical timerange starts 2022-01-01 and needs warm-up before it,
  so on NDAX's own candles the 4h strategies would have a shorter canonical range.
- **Gaps.** One missing 1d candle (2024-02-26/27) on every pair. Ten single missing 4h candles
  on every pair, at the same timestamps across pairs, so these are venue outages, not
  thin-market gaps.
- **No bulk archive** was found. Kraken's official archive (ADR-0020) has no NDAX equivalent
  as far as this spike looked; REST paging (1,000 candles per call) is the only source.

### Freqtrade dry-run

Config: `config.dry_run.json` with `exchange.name: ndax`, `stake_currency: CAD`, the six CAD
pairs, empty key/secret, no Telegram/API server, `Baseline4h`. With
`stoploss_on_exchange: false` (as in the dry-run config today):

```
Exchange "ndax" is known to the ccxt library, available for the bot, but not officially supported by the Freqtrade development team.
No Ndax specific subclass found. Using the generic exchange class instead.
Whitelist with 6 pairs: ['BTC/CAD', 'XRP/CAD', 'ETH/CAD', 'SOL/CAD', 'LINK/CAD', 'LTC/CAD']
Refreshing candle (OHLCV) data for 6 pairs
Converting candle (OHLCV) data to dataframe for pair ETH/CAD. ... Dropping last candle   (x6)
TA Analysis Launched / Ended ...
Bot heartbeat. PID=1, version='2026.8', state='RUNNING'
```

No errors over ~3 minutes. Two caveats: dry-run fills are priced from ccxt's hard-coded
**0.25 %** taker fee, not NDAX's 0.20 %, unless a `fee` override is set; and no trade was
entered in the window, so the order-simulation path itself was not exercised.

### Stop-loss on exchange

- ccxt: `createStopOrder`, `createStopMarketOrder`, `createStopLimitOrder` are `True`. NDAX's API
  has `StopMarket`, `StopLimit`, `TrailingStopMarket`, `TrailingStopLimit` order types.
- Freqtrade 2026.8: `stoploss_on_exchange` is allowed only when the exchange's class sets it in
  `_ft_has`. NDAX has no class, so the generic default (`False`) applies. With it set to `true`:
  `ConfigurationError: On exchange stoploss is not supported for NDAX.` The bot does not start.
- So on NDAX the stop lives only in the bot. If Freqtrade, the VPS or the network is down, an
  open position has no stop. ADR-0019 chose an exchange-held stop precisely for this case.
  Getting one back means either a custom exchange subclass (code outside the pinned image, needs
  its own ADR and tests) or accepting bot-side stops (an ADR superseding part of ADR-0019).

### Credentials and the no-withdrawal rule

- `ccxt.ndax.requiredCredentials` = `apiKey`, `secret`, `uid`, **`login`, `password`** (the
  comment in ccxt says the last two are "required for signIn() and withdraw()").
  `check_required_credentials()` runs on every private call, so all five must be set even
  though requests are signed with API key + secret + user id (HMAC). `fetch_accounts` also
  refuses to run without `login` (it sends the user name). Freqtrade's balance call needs an
  account id, so this path is likely hit.
- Whether **dummy** login/password values would satisfy ccxt while the real authentication
  uses only the API key is **untested**: that needs a real key, out of scope here.
  `withdraw()` additionally needs a 2FA secret, which this system must never hold.
- NDAX's official API docs (<https://apidoc.ndax.io/>) say "Permissions handle the rules that
  determine what a user can access and do… trading, depositing, or withdrawing funds… An
  administrator with Operator permission sets up a user's permissions." They don't document
  per-API-key scopes. A third-party import guide (CoinLedger) describes an "Allow Read Only"
  option when generating a key. **Whether NDAX can issue a trade-only key without withdrawal
  permission is unverified.** It's a hard gate under CLAUDE.md §0 rule 2.
- **Update 2026-10-30.** The NDAX UI now offers per-key permissions (read, deposits,
  withdraws, trading), and a read-only key exists. `scripts/ndax-access-check.sh --scope
  read-only` (VPS, key from `.env`, ccxt given fixed dummy login/password, never `signIn`)
  tests it. Its probes use only reads and quotes. The doc lists each call's permission:
  `GetAccountPositions` / `GetOpenOrders` / `GetUserAccounts` accept `AccountReadOnly`;
  `GetOrderFee` and `SendOrder` need `Trading`; `GetWithdrawFee` needs `Trading` or `Withdraw`.
  ccxt's private calls are HMAC-signed with uid + key + secret and never send the password.
  `login` is sent only as `UserName` on `GetUserAccounts`, which is the step the dummy value
  might break. The script also tries that call without `UserName`. Two API facts from
  `apidoc.ndax.io` (2026-10-30): **no IP-whitelist call and no API-key/permission query is
  documented**. The probe tries the undocumented `GetUserPermissions` for information only. A
  wrong key gets HTTP 500, not 401. **Whether dummy credentials work: TBD**, until the script
  runs on the VPS with the real read-only key.
- **Update 2026-10-30, first VPS run (read-only key): FAIL, and the outcome is NO for live
  use.** What the run showed, and what each finding turned out to mean:
  1. `GetAccountPositions` / `GetOpenOrders` answered `OMSId and AccountId must be Integers`,
     and the old classifier counted that as "allowed". That was a bug: any error that wasn't a
     refusal counted as allowed. Fixed. Now only a clean success is "allowed", only an explicit
     `Not Authorized` (errorcode 20) or HTTP 401/403 is "denied", and everything else is
     "unknown", which fails. The probe also sent both `omsId` and `OMSId`. The doc says key
     case doesn't matter, so that was probably a duplicate key. It now sends `OMSId` +
     `AccountId` once each, in the doc's casing. The signed request got past authentication
     to the handler, so key-only signing seems to work for reads. Not yet confirmed.
  2. `GetOrderFee` / `GetWithdrawFee` returned `404 NOT FOUND`. **The names are right**: both
     are in `apidoc.ndax.io` with those exact names. Checked without a key: NDAX's HTTP gateway
     gives `404 NOT FOUND` to every private call (`GetAccountPositions` included) and to a
     made-up name, on GET and POST. Public calls get 200. So a 404 means nothing about
     permissions. `GetDepositInfo` is not in the doc and was dropped. No documented read call
     is gated by the Deposit permission alone, so deposit isn't probed.
  3. `GetUserPermissions` returned `Deposit, Trading, Withdraw`. That call is not in
     `apidoc.ndax.io` and takes a `UserId`. The doc describes permissions only per user ("an
     administrator … sets up a user's permissions"). Outside `AuthenticateUser`'s request
     fields, the doc never mentions API keys: no call lists keys or their scopes. So this is
     the **user's (account-level) permission set**. It can't show the key's scope, and the
     API has no call that does.
  - No login needed: ccxt runs with `requiredCredentials` login/password switched off and
    the numeric account id preset (`accounts` + `options.accountId`, from `NDAX_ACCOUNT_ID`
    or a key-signed `GetUserAccounts` with `UserId` only). That way `fetch_accounts`, the only
    call that uses the login, never runs. Freqtrade can pass the same settings through
    `ccxt_config`. Untested in Freqtrade: TBD (Phase 2), moot unless the verdict changes.
  - **Verdict.** The key-only signing gap looks closable. Key-scoped permissions **cannot be
    verified** through NDAX's documented API. The one permission report available says this
    login holds Withdraw, and the only behavioural test (a Trading/Withdraw fee quote) came
    back 404, which proves nothing. CLAUDE.md §0 rule 2 needs proof that the key cannot
    withdraw. NDAX can't give that proof, so **NDAX will not be used live.** Only one result
    could reopen this: a re-run of the fixed check (`scripts/ndax-access-check.sh --scope
    read-only`) where `GetWithdrawFee` returns an explicit `Not Authorized` (errorcode 20). A
    404 or any other answer keeps the verdict.
- Security note: searching for NDAX API docs returns several lookalike domains
  (`*.pages.dev`, `daftpage.com`) styled as NDAX pages. Only `ndax.io` and `apidoc.ndax.io` were
  used here. Any key-creation runbook must pin the real domain.

## What would change

### Conductor

| Area | Change | Size |
|---|---|---|
| `application/live_guard.py:38` | Live start refuses any exchange but `kraken`. Must accept `ndax` (and its test) | Small, but it is a live-path guard: needs an ADR first |
| Money terms (ADR-0012), `PRINCIPAL_USD`, `DAILY_PROFIT_CAP_USD`, `stake_currency` | NDAX is CAD-only, so ADR-0008 (USD quote) must be superseded. Principal, profit cap and loss limits become CAD figures. R1's "$100" needs a ratified CAD amount | Requirements + ADR + config + tests |
| `domain/tax.py` (NFR6) | Today: USD fills converted to CAD with an `FxRate`. With CAD fills, the conversion is identity. Simpler, but the domain types are USD-named and the FX ingest becomes unused | Medium refactor; tax tests are mandatory (money path) |
| Ledger history | Third-party report (CoinLedger) says NDAX's API returns only ~3 months of trades. Ingest must never fall behind by that much, and backfill after a long outage may be impossible. **Unverified** | Runbook + alert |
| Operator messages (`fence.py:140`, `cli.py:32`, dashboard) | "on Kraken" wording | Trivial |
| Freqtrade REST client, halts, risk cycle | Venue-agnostic (they talk to Freqtrade, not the exchange) | None |

### R5 (account isolation)

The R5 code is venue-agnostic: it compares Freqtrade-reported balances per base asset with
ledger holdings. What changes:

- The held-asset blacklist (`pair_blacklist`: ACA, ADA, DOT, KAVA, SC, XTZ) is a fact about
  **the Kraken account**. A new NDAX account starts empty, so the list would be re-derived from
  that account's balances at sign-up.
- NDAX offers Staking/Auto Earn (fee page: "20% of total generated rewards"). If any asset in
  the account is enrolled, how its balance appears to `fetch_balance` (and so to R5) is
  unknown. **TBD (Phase 3)**: confirm with a real account; simplest rule is "never enrol
  anything in this account".
- The R5 startup check needs a real balance read, which brings back the credentials question
  above.

### Access check (`scripts/kraken-access-check.sh`, `kraken_access_probe.py`)

Entirely Kraken-specific and would be rewritten, not adapted. It relies on Kraken's
`AddOrder validate=true` (a dry order the exchange checks then discards), on `WithdrawInfo`
/`DepositMethods` returning "permission denied" for a correctly scoped key, and on Kraken's
per-key IP whitelist. Whether NDAX offers a validate-only order, permission-denied responses
per key, or IP-restricted keys is **unknown** (not in the official API docs as read here).
Without those, the check can't prove "this key cannot withdraw" the way it does today. This
is the same gate as the credentials question.

### Backtest cost model and data

- `config.backtest-costs.json`: fee 0.0020 plus a **spread-based** slippage term, not Kraken's
  0.0010. From this snapshot, ~0.0029 mean half-spread (BTC/ETH/SOL ~0.0020, LINK/LTC
  ~0.0035–0.0045) gives **≈ 0.0050 per side**. One overnight snapshot is too thin to fix the
  number: **TBD (Phase 3)**, from a week of sampled books at the strategy's decision times.
  Per-pair slippage would be more honest than one average; the harness takes one number today.
- Data: the harness reads only `data/kraken` and `fixtures/kraken-markets.json`. NDAX-candle
  backtests would need an NDAX ingest (REST paging, close→open label shift, gap report, a
  snapshot id), an NDAX markets fixture, and a supersession of ADR-0020. The 4h canonical range
  would start later than 2022-01-01.

## Harness: C05 and C04 at NDAX's fee vs Kraken

**Same candles, different fee.** The runs below use the Kraken archive (USD candles, snapshot
`6f4979b22d6aaafe`) at **0.0030 per side** (NDAX 0.20 % + the same 0.10 % slippage buffer
Kraken's model uses). That isolates the fee rate. They are not NDAX-candle backtests (above),
and they underprice NDAX's spread; the harness's automatic 2× stress (0.0060) is the closer
estimate of NDAX's real cost (~0.0050).

These are **registered trials** (fee is part of trial identity), so the registry's N went from
4 to 6. Changing venue after seeing the Kraken results is itself a selection step; the trial
count is there to charge for it. The 0.0030 overlay was committed (574ab4c) and reverted
(3038b97) on this branch only; `main`'s cost file is unchanged at 0.009.

| | C05 Kraken | **C05 NDAX fee** | C04 Kraken | **C04 NDAX fee** |
|---|---|---|---|---|
| Trial id | dab671223355 | 7d418e2c3ea6 | 4b08ad68cc6a | f2d85e2482d9 |
| Fee per side | 0.009 | 0.003 | 0.009 | 0.003 |
| Trades / force exits | 240 / 2 | 240 / 2 | 236 / 2 | 239 / 2 |
| Net profit ($100 start) | −$61.48 | **+$59.07** | −$29.84 | **+$12.81** |
| CAGR | −18.2 % | +10.3 % | −7.2 % | +2.6 % |
| Daily-equity Sharpe | −0.14 | **0.44** | −0.38 | 0.24 |
| Max drawdown | 83.2 % | 71.4 % | 38.0 % | **20.6 %** |
| Win rate | 22.9 % | 29.2 % | 25.0 % | 32.6 % |
| Fees paid | $152.09 | $108.62 | $55.39 | $23.05 |
| Net + fees ("gross", not compounded) | +$90.61 | +$167.69 | +$25.55 | +$35.86 |
| Fee ratio | 39.6 % | 13.7 % | 47.1 % | 15.7 % |
| 2× stress: fee / net / Sharpe / MDD | 0.018 / −$94.12 / −0.94 / 94.7 % | **0.006 / −$21.58 / 0.15 / 78.0 %** | 0.018 / −$60.30 / −1.08 / 64.1 % | **0.006 / −$9.76 / −0.05 / 28.1 %** |
| WF anchored IS mean / pooled OOS | −0.12 / −0.16 | 0.43 / 0.41 | −0.62 / −0.54 | −0.06 / 0.07 |
| WF rolling IS mean / pooled OOS | −0.11 / −0.16 | 0.47 / 0.41 | −0.44 / −0.54 | 0.16 / 0.07 |
| OOS windows with Sharpe > 0 | 6 / 15 | 6 / 15 | 5 / 15 | 6 / 15 |
| Null Sharpe median / p95 | −0.41 / −0.04 | 0.05 / 0.42 | −0.41 / −0.14 | 0.18 / 0.43 |
| Candidate's null percentile | 86.5th | **97th** ✅ | 56th | 66.5th |
| MDD vs null median | 83.2 vs 90.5 ✅ | 71.4 vs 77.4 ✅ | 38.0 vs 37.9 ❌ | 20.6 vs 24.4 ✅ |
| Top-trade share of gross wins vs null median | 23.5 vs 10.1 ❌ | 26.5 vs 10.1 ❌ | 9.5 vs 9.6 ✅ | 9.1 vs 9.6 ✅ |
| Largest trade ÷ net profit | n/a (net < 0) | **355 %** | n/a (net < 0) | **105 %** |
| Force-exit group ÷ net profit | n/a (net < 0) | 40 % ($23.40) | n/a (net < 0) | 51 % ($6.49) |
| DSR / PSR vs 0 (registry, N = 6) | 0.08 / 0.38 | 0.45 / 0.83 | 0.03 / 0.20 | 0.29 / 0.70 |
| **Gate 1** | **Fail** | **Fail** | **Fail** | **Fail** |

BTC/USD buy-and-hold over the same range, no fees: +75.0 %, Sharpe 0.49, MDD 67.0 %.

### Gate 1 at NDAX's fee

| Criterion | C05 NDAX fee | C04 NDAX fee |
|---|---|---|
| ≤ 6 parameters | ✅ | ✅ |
| IS Sharpe ≥ 1.0 | ❌ 0.44 | ❌ 0.24 |
| ≥ 8 OOS windows, both schemes | ✅ 15 | ✅ 15 |
| Pooled OOS ≥ 50 % of IS | ❌ (fails at the IS floor; the ratio alone is met: 0.41 vs 0.44) | ❌ (0.07 < 0.12, and the IS floor) |
| ≥ 100 trades | ✅ 240 | ✅ 239 |
| Fee ratio < 40 % | ✅ 13.7 % | ✅ 15.7 % |
| Single trade ≤ 30 % of net | ❌ 355 % | ❌ 105 % |
| Force-exit group ≤ 30 % of net | ❌ 40 % | ❌ 51 % |
| Beats random-entry null | ❌ (Sharpe ✅ 97th, MDD ✅, concentration ❌) | ❌ (Sharpe 66.5th) |

### What this says

- **Fees were most of the gap, not all of it.** Cutting the fee from 0.90 % to 0.30 % per side
  turns both candidates profitable and changes nothing else: same signals, near-identical trade
  counts. C05 at 0.44 Sharpe roughly matches BTC buy-and-hold's 0.49, with a larger drawdown.
- **C05's entry edge shows up once costs drop.** At Kraken's fee it was at the null's 86.5th
  percentile; at NDAX's fee, the 97th. Both the candidate and its null pay the same fee, so the
  percentile isn't just the fee shifting everything. The edge is still not tradeable as a Gate 1
  pass: a few trades carry the profit (the largest is 3.5× net profit) and the 2 open trades
  force-closed at the end are 40 % of it.
- **C04 is still indistinguishable from random entry** (66.5th percentile), as on Kraken. It
  has the lowest drawdown of anything run so far (20.6 %), because of its vol sizing.
- **The spread decides it.** At 2× (0.60 % per side, a bit above the ~0.49 % measured on NDAX),
  C05 loses $21.58 and C04 loses $9.76. NDAX's real cost sits between the two columns, closer to
  the 2× one. NDAX at its real cost was not run; it needs the spread number first (TBD above).
- DSR is reported, not gated: 0.45 and 0.29, well below the review's suggested 0.80, at N = 6.

## Recommendation

Do not switch venues on this evidence. If the cost advantage is worth pursuing, the order
that avoids wasted work is:

1. **Human, with an NDAX account (no code):** confirm in NDAX's key-creation screen whether a
   key can trade without withdrawal permission, and whether it can be IP-restricted. Ask NDAX
   support whether the API needs the account password. If either answer is "no", stop here: §0
   rule 2 rules NDAX out for live trading regardless of cost.
2. Decide by ADR whether bot-side stops are acceptable, or whether a custom Freqtrade exchange
   class for NDAX stop orders is in scope. Without one of these, ADR-0019's design does not
   carry over.
3. Sample NDAX books for a week at 4h/1d decision times to fix the per-side slippage number,
   then run the registered candidates at NDAX's **real** cost. Ideally also run them on NDAX's
   own (label-shifted) CAD candles.
4. Only then: superseding ADRs for ADR-0002 (venue), ADR-0008 (USD → CAD) and ADR-0020 (data),
   the R1 principal in CAD, and the Conductor/R5/access-check work listed above.

Independently of the venue, these results suggest **the slower C05 "variant B" (weekly evaluation; see
[05](05-first-candidates.md#what-this-does-and-does-not-show)) on Kraken** is still worth running as the next trial. It
attacks the same cost problem by trading less, without any of the venue risk.

## Not verified here

- Whether NDAX is registered in Canada and how (not checked; Kraken's own status is risk T3).
- Any private-endpoint behaviour: order placement, stop orders, balance format, fee actually
  charged, the API's trade-history window.
- Spread at other times of day; this is one overnight snapshot.
- Whether an NDAX bulk OHLCV archive exists anywhere other than the REST API.

## Reproducing

```bash
# Probes (public endpoints, pinned image): see scripts/spike_ndax/README.md
docker run --rm -v "$PWD/scripts/spike_ndax:/probe:ro" --entrypoint python \
  freqtradeorg/freqtrade:2026.8 /probe/03_4h_depth_and_labels.py

# Harness at NDAX's fee: check out 574ab4c (the 0.003 overlay), then
scripts/research-harness.sh run C05EmaFlip4h --out /out/ndax   # refused now: already registered
scripts/research-harness.sh registry                            # all 6 trials, DSR at N = 6
```

Full run reports: `services/research/runs/ndax/{C05EmaFlip4h,C04TsmomVolScaled1d}.json`
(git-ignored, local).
