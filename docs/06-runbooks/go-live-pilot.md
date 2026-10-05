# Runbook — Go live: the $20 pilot on Kraken

**What this is:** the one-time procedure that takes the system from dry-run to **real money**
for the pilot decided in [`ADR-0019`](../05-adr/0019-live-pilot-20-usd-plumbing.md): a **$20**
principal, `Baseline4h` (a strategy known to have **no edge**), **one position at a time**,
to prove the real-exchange plumbing. It is not an attempt to make money. The other $80 is **not**
deposited and stays gated behind Gate 2.

**Related:** [`kill-switch.md`](kill-switch.md), [`nuclear-protocol.md`](nuclear-protocol.md),
[`start-stop.md`](start-stop.md) ("R5 abort"), [`key-rotation.md`](key-rotation.md),
[`restore-backup.md`](restore-backup.md), [`rebuild-vps.md`](rebuild-vps.md).

**Time:** Part A is spread over days (it waits for the soak). Parts B-D take about 1.5 hours.
Part E is the first day, then the first real position (which can take days).

**Rules (read them; they are why this is safe):**
- You can lose the $20. You cannot lose more through this system: the key cannot withdraw, and
  Kraken only ever holds what you put in it.
- **Never put a key with Withdraw or any Funding permission in `.env`.** If a check says the key
  can withdraw, stop and delete that key on Kraken that minute.
- **Never skip, force or shorten a gate.** `scripts/trading-mode.sh live` has no such options on
  purpose. If a gate fails, fix the cause; do not look for a way around.
- The only thing that places orders is Freqtrade. Nothing in this runbook, and nothing the LLM or
  Conductor can do, places one (ADR-0003). Conductor can only pause, flatten and stop.
- If anything is not as the "Expected" line says: stop, do not continue to the next step.
  If real money is at risk and you are unsure, `/kill` first, ask questions second.

## Part A — Before you fund anything

### A1. Decisions you must make consciously

Tick each, in your head or on paper, before going on:
- [ ] **Tax.** Real trades are taxable events. Whether they are business income or capital
  gains is **not decided** ([`../09-tax-questions.md`](../09-tax-questions.md); risk register
  T1/T4); the accountant has not been consulted. The ledger records a CAD value for every
  closed trade from the first one (`conductor.cli export-tax`), so nothing is lost by
  deciding later. You are choosing to proceed, or you have asked the accountant. Either is
  fine; ticking it without thinking is not.
- [ ] **You accept losing the $20.** `Baseline4h` is expected to lose a little to fees and spread.
- [ ] **What the exchange stop does and does not do.** Each position gets a real **stop-loss order on
  Kraken** (`stoploss_on_exchange`, ADR-0019), so if the VPS or Freqtrade is down the position is
  still sold if the price falls to the stop. It is a market sell (normal slippage), it does not
  run the strategy's exit signals or Conductor's halts while the bot is down, and for roughly
  the first 10 seconds after an entry fills Kraken holds only a very wide initial stop. At $20
  that is accepted.

### A2. Everything is merged and deployed

On the Mac, check that `main` contains the live-pilot work and deploy it:
```
git switch main
git log --oneline -20 | grep -i "live pilot\|live-pilot"
make deploy
```
Expected: the log shows the pilot commits (merge of `feat/live-pilot`), and `make deploy`
ends with both containers `Started` or `Running`. (`make deploy` ships the committed state
of `main`, in whatever mode the server is in.)

Then on the VPS (`make ssh`, `cd /opt/ai-trading-agent`):
```
scripts/trading-mode.sh status
scripts/drill-check.sh --expect-halts 0
```
Expected: `mode: dry-run`, both containers `Up`, and `CHECK PASS`. If a halt is active, clear
it first ([`kill-switch.md`](kill-switch.md)); a soak with an active halt does not pass.

### A3. Create a QUERY-ONLY Kraken key and test access from the VPS

Purpose: prove that Kraken accepts calls from the VPS's IP **before** any real key exists. This
key can read balances and do nothing else.

1. Log in to Kraken directly in a browser (not through anything automated). Go to
   **Security → API → Create API key**.
2. Name it `ai-trader-vps-query-only`. Tick **only**:
   - Funds permissions: **Query** (nothing else in that group: not Deposit, not Withdraw)
   - Orders and trades: **nothing**
   - Data: Query ledger entries (optional)
3. Under key restrictions, set the **IP address whitelist** to `203.0.113.10` (the VPS's static
   IPv4: `terraform -chdir=infra/terraform output -raw ipv4` prints it).
4. Click Generate. Kraken shows the **API key** and the **private key (secret)** once. Copy both
   into LastPass now (entry: `ai-trader kraken query-only key`).
5. On the Mac, put them in `.env` (never commit it): set `KRAKEN_API_KEY=` and
   `KRAKEN_API_SECRET=` to those values. Then:
   ```
   make push-env
   ```
   Expected: `pushed .env -> ai-trader-vps:/opt/ai-trading-agent/.env (root:deploy 0640)`.
   (It is allowed because `TRADING_MODE` in `.env` stays `dry_run`.) The running dry-run stack
   does **not** pick this up: its containers never hold the key.
6. On the VPS:
   ```
   scripts/kraken-access-check.sh --scope query-only
   ```
   Expected, in order: `outbound IP of this host: 203.0.113.10 (key must be whitelisted to
   203.0.113.10)`, a `key fingerprint:` line, then
   ```
   ok   Query funds (Balance)            got allowed  expected allowed
   ok   Query open orders                got allowed  expected allowed
   ok   Create orders (validate-only)    got denied   expected denied
   ok   Funding: deposit                 got denied   expected denied
   ok   Funding: WITHDRAW                got denied   expected denied
   KRAKEN ACCESS CHECK PASS (query-only)
   ```
   - `FAIL: cannot read the balance ...` → wrong key/secret, or the IP is not whitelisted. Check
     the `outbound IP` line: if it is not `203.0.113.10`, the whitelist must be that IP instead.
   - A `FAIL ... Funding` line → the key has permissions it must not have. Delete it on Kraken,
     create it again exactly as above.

### A4. Know what is already on the account (R5)

The system only trades what it buys itself. Look at your **Kraken → Portfolio** page now and
write down every asset you hold and how much. The blacklist already covers ADA, ETH, DOT, SC,
KAVA, ACA, XTZ and USDC, and ETH/USD is removed from the pilot whitelist. The pilot whitelist is
**BTC, XRP, SOL, LINK, LTC**.
- If you hold any of those five: R5 will stop the go-live (that is correct) and you will clear
  it in Part D with "R5 abort" in [`start-stop.md`](start-stop.md). Better: decide now whether it
  is yours to keep (you will exclude it) or should leave the account.
- If you already hold **USD** on the account: it is not exposure the system trades, and the bot's
  stake is capped at 19 USD by configuration regardless of balance. But note it: the pilot
  principal is the $20 you add, not the USD that was already there.

### A5. Wait for the soak, then check it

The pilot needs a **72-hour clean soak counted from 2026-10-05 15:29 UTC**
(`infra/live/soak-start`), i.e. not before **2026-10-08 15:29 UTC**. On the VPS:
```
docker exec ai-trading-agent-conductor python -m conductor.cli soak-check --started-at "$(cat infra/live/soak-start)"
```
Expected once it is time: `soak started 2026-10-05 15:29Z; elapsed 72.x h of 72.0 h` and
`SOAK MET`. `SOAK NOT MET: not enough time` means wait. `SOAK NOT CLEAN` lists a halt the
system raised itself (a risk breach) or one still active: understand it, clear it per
[`kill-switch.md`](kill-switch.md), and, because the rule is "clean", decide with eyes open
whether to move `infra/live/soak-start` later (a reviewed commit, then `make deploy`).

The ledger cannot see Conductor downtime. Open the healthchecks.io page for this system and read
its log for the soak window: any **down** period other than the drill-4 outage on 2026-10-05
(5 min 42 s) is a reason to wait longer. This step is yours; no script checks it.

**Do not go on until the soak is met.** Parts B and C can be done while waiting.

## Part B — Fund the account: about $28 CAD → $20 USD

Why $28 CAD: $20 USD at an exchange rate of about 1.40 CAD per USD is about $28 CAD. Check the
current rate on the Kraken buy screen and adjust; fees come on top of what you want to end up
with. **What matters is that you end with exactly 20.00 USD to trade with; the CAD you send is
whatever it takes.**

1. Kraken → **Funding → Deposit → Canadian dollar (CAD) → Interac e-Transfer**. Read the fee and
   limit lines on that screen. Send the amount. Write down: the CAD amount, the date and time,
   the Interac reference. **This is your R1 deposit record**; store it in LastPass notes with
   the conversion record below (the ledger records the principal automatically at first start,
   but the deposit evidence is on Kraken's side and yours).
2. When the CAD shows as available, convert it: **Trade → Buy USD with CAD** (the USD/CAD
   market), a market or limit order for **exactly 20.00 USD**. Write down the fill price, the
   fee and the time (they are the cost basis for the tax record).
3. Check **Portfolio**: you hold at least **20.00 USD** (more only if you held USD before, A4).
   Leftover CAD, if any, is not touched by the system; leave it.

Expected: USD balance ≥ 20.00. If it is slightly under 20 after fees, convert the difference now.
Do not start with less than 20: the ledger's principal is pinned at 20 (R1) and the bot sizes
a 19 USD position from it.

## Part C — The real key: query + create/cancel orders, no funding, no withdraw

Follow the "create new, verify, then revoke the old one" rule of
[`key-rotation.md`](key-rotation.md).

1. Kraken → **Security → API → Create API key**. Name: `ai-trader-vps-live`. Tick **exactly**:
   - Funds permissions: **Query** only. **Not Deposit. Not Withdraw.**
   - Orders and trades: **Query open orders & trades**, **Query closed orders & trades**,
     **Create & modify orders**, **Cancel & close orders**
   - Data: Query ledger entries (optional)
2. **IP address whitelist: `203.0.113.10`.** No other IP.
3. Before you click Generate, read the permission list back on Kraken's confirmation screen and
   check, in words: *withdraw is off; deposit is off*. This is the step that is easiest to get
   wrong when tired.
4. Generate. Copy the API key and private key into LastPass now (`ai-trader kraken LIVE key`).
5. On the Mac replace `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` in `.env` with the new pair and
   `make push-env`. Expected: `pushed .env -> ...`.
6. On the VPS:
   ```
   scripts/kraken-access-check.sh --scope trade
   ```
   Expected:
   ```
   ok   Query funds (Balance)            got allowed  expected allowed
   ok   Query open orders                got allowed  expected allowed
   ok   Create orders (validate-only)    got allowed  expected allowed
   ok   Funding: deposit                 got denied   expected denied
   ok   Funding: WITHDRAW                got denied   expected denied
   KRAKEN ACCESS CHECK PASS (trade)
   ```
   `got allowed` on `Create orders` here means Kraken accepted a **validate-only** order check
   (nothing was placed; the probe order is also far below Kraken's minimum). A `FAIL` on
   `Funding` or `WITHDRAW` means **the key can move money: delete it on Kraken now** and
   recreate it without Funds permissions.
7. Revoke the query-only key on Kraken (Security → API → delete `ai-trader-vps-query-only`).

`scripts/trading-mode.sh live` runs this same trade-scope check again as a gate, so a key
changed between now and the switch cannot slip through.

## Part D — The switch

Only when: soak met (A5), account funded (B), real key verified (C).

1. On the VPS, in `/opt/ai-trading-agent`:
   ```
   scripts/trading-mode.sh live
   ```
   (From the Mac: `make go-live`.) It prints each gate; nothing is stopped until the first four
   pass. Expected, in order:
   ```
   == Gates (nothing has been stopped or changed yet)
     soak started 2026-10-05 15:29Z; elapsed 7x.x h of 72.0 h
     SOAK MET
   PASS soak
     KRAKEN ACCESS CHECK PASS (trade)
   PASS key scopes
   PASS ledger: no live volume yet (a fresh one is created empty)
   == Stopping the dry-run stack and archiving its ledger
     archived: archive/dry-run-ledger-<time>.tgz and archive/dry-run-freqtrade-<time>.tgz
   == Starting Freqtrade in LIVE config, paused (it cannot trade yet)
     freqtrade says: dry_run=False state=paused positions=0 orders=0
   PASS mode
   == R5 account isolation against the real Kraken balances
     R5 CHECK PASS
   PASS R5
   == Starting the live Conductor
   LIVE. ...
   ```
   Any `REFUSED:` line stops it with the reason. Nothing is half-done in a dangerous way: until
   `LIVE.` the only thing running is a **paused** live Freqtrade, which cannot open a position.
   - `FAIL soak` / `FAIL key scopes` / `FAIL ledger`: nothing was changed. Fix the cause; run it again.
   - `archive failed`: the dry-run stack was restarted for you; nothing else changed.
   - `gate MODE`: Freqtrade did not come up as live+paused. State is `live-pending`; look at
     `docker logs ai-trading-agent-freqtrade --tail 80`; then `scripts/trading-mode.sh live`
     again, or back out with `scripts/trading-mode.sh dry-run`.
   - `R5 gate failed`: state is `live-pending`. Follow "R5 abort" in
     [`start-stop.md`](start-stop.md), then run `scripts/trading-mode.sh live` again (it skips
     the soak, which the dry-run ledger has already proved, and repeats the rest).
2. Confirm it is live and sane:
   - Telegram shows `*** LIVE: REAL MONEY *** Conductor started: ... mode=live ...`. Send
     `/status`: the first line is `*** LIVE: REAL MONEY *** Mode: live`.
   - The dashboard (`https://ai-trader-vps.<tailnet>.ts.net/`) has a red **LIVE: REAL MONEY** bar.
   - On the VPS: `scripts/drill-check.sh`. Expected: `freqtrade` `paused`, then within about a
     minute `running` (Conductor starts it when no halt is active); `dry_run: False`; the `data`
     section shows `principal=20 USD trades=0`.
   - `scripts/trading-mode.sh cli capital` → `principal: 20`, `max_deployed_capital: 20`.
3. Within a day, check the first nightly backup ran (03:15 UTC) and, once, `docker exec
   ai-trading-agent-conductor python -m conductor.cli backup-now` → `conductor: ok ...`
   and `freqtrade: ok ...`. Both keys now start `backups/live/` (live and dry-run backups are
   kept apart: the dry-run ones are `backups/dry_run/` or, if made before the split,
   `backups/<source>/`). The dry-run ledger is also in `archive/` on the VPS: copy `archive/`
   to the Mac once, then it can stay. Prove the live backup restores, from the Mac with a B2
   **read** key ([`restore-backup.md`](restore-backup.md) Part A):
   `scripts/restore-test.sh --mode live all` → `RESTORE TEST PASSED`, `(mode: live)`,
   `principal: 20 USD`. (`--mode dry_run` would show `100 USD`: that is how you know which
   ledger you are holding.)

**To go back to dry-run at any time:** `scripts/trading-mode.sh dry-run` (`make go-dry-run`).
It refuses while a real position or order is open (flatten first: `/flatten`, then confirm flat
on Kraken) or while it cannot tell. It keeps the live ledger volume. It does **not** remove the
key from `.env`: if the pilot is over, blank `KRAKEN_API_KEY`/`KRAKEN_API_SECRET` in `.env`,
`make push-env`, and delete the key on Kraken.

## Part E — First-day checks against the real exchange

Goal: prove, with real orders, the things dry-run cannot. `Baseline4h` trades on 4-hour candle
closes (00, 04, 08, 12, 16, 20 UTC) and enters rarely, and **nothing here can force an entry**
(no Conductor command opens a trade; `force_entry_enable` is off). So E1-E3 need no position and
are done at once; E4 happens when the first real position appears, which may take days.

Have your phone with Telegram and the Kraken website open. Keep `scripts/drill-check.sh --watch 2`
running in a second terminal on the VPS.

### E1. Kill switch against the real Freqtrade (no position)

1. Telegram: `/kill`, then the `yes <code>` it asks for, within 60 seconds.
   Expected reply: `Kill switch #<n>: all steps ok`. The `--watch` lines go from
   `freqtrade=running` to `freqtrade=paused` within ~10 s, `halts=1`.
2. Telegram: `/resume <n>`, then `yes <code>`. Expected: `Cleared halt #<n>.` and `freqtrade=running`.

### E2. Nuclear against the real Freqtrade (no position)

1. Telegram: `/flatten`, `yes <code>`. Expected: `Nuclear #<n>: all steps ok` listing `pause_entries`
   and `stop` (no `force_exit_all` because nothing is open) and `confirm_flat: ok`.
   `--watch` shows `freqtrade=stopped`, `halts=1`. **Only one** result message arrives (not two).
2. Kraken → **Orders** (open orders): none. Portfolio unchanged.
3. `/resume <n>`, `yes <code>`. Expected: `Cleared halt #<n>.`, `freqtrade=running`.

### E3. Read-only plumbing

- `scripts/trading-mode.sh cli isolation-check` → `R5 CHECK PASS`.
- Re-record the `/balance` fixture (Phase 4 TODO): on the VPS
  ```
  docker exec -i ai-trading-agent-freqtrade python - <<'PY'
  import base64, json, os, urllib.request
  tok = base64.b64encode(f"{os.environ['FREQTRADE__API_SERVER__USERNAME']}:{os.environ['FREQTRADE__API_SERVER__PASSWORD']}".encode()).decode()
  r = urllib.request.Request("http://127.0.0.1:8080/api/v1/balance", headers={"Authorization": "Basic " + tok})
  print(json.dumps(json.load(urllib.request.urlopen(r, timeout=8)), indent=2))
  PY
  ```
  Expected: JSON with a `currencies` list that includes your **real** holdings. Copy it to the
  Mac, **replace every amount with a round dummy number** (the repo must stay safe to publish,
  NFR7; keep the keys, types and the shape) and commit it as
  `services/conductor/tests/fixtures/freqtrade/balance.json` on a branch with
  `docs(fixtures): re-record /balance from the live instance`; run `make conductor-test`.

### E4. With the first real position: the drills that matter

When Telegram shows a trade opened (Conductor sends an alert for each entry/exit) and
`scripts/drill-check.sh` shows `open positions: 1`:

1. **Look at Kraken first**: the position is real, on the exchange, the size is about 19 USD of
   one of BTC/XRP/SOL/LINK/LTC, and it is the only position. Note the pair and amount.
2. **Confirm the stop order is visible on Kraken** (the whole point of `stoploss_on_exchange`).
   Wait **at least 30 seconds** after the entry filled, then on Kraken → **Orders → Open orders**
   look for exactly **one** order on that pair: side **Sell**, type **Stop loss** (a market
   stop-loss), volume equal to the position amount, and a trigger price **below** the current
   price. Compare its trigger price with what Freqtrade believes. On the VPS:
   ```
   docker exec -i ai-trading-agent-freqtrade python - <<'PY'
   import base64, json, os, urllib.request
   tok = base64.b64encode(f"{os.environ['FREQTRADE__API_SERVER__USERNAME']}:{os.environ['FREQTRADE__API_SERVER__PASSWORD']}".encode()).decode()
   r = urllib.request.Request("http://127.0.0.1:8080/api/v1/status", headers={"Authorization": "Basic " + tok})
   for t in json.load(urllib.request.urlopen(r, timeout=8)):
       print(t["pair"], "open_rate", t["open_rate"], "stop_loss_abs", t["stop_loss_abs"], "initial_stop_loss_abs", t["initial_stop_loss_abs"])
   PY
   ```
   Expected: Kraken's trigger price equals `stop_loss_abs` (to the pair's price precision), a few
   percent below `open_rate`. If you looked within the first ~10 seconds you may instead have
   seen the very wide initial stop (about 1% of the price, `initial_stop_loss_abs`): refresh;
   it is replaced by the real stop. **If there is still no stop order after a minute, or two,
   or the volume is wrong: do not leave the position as it is. `/flatten`, confirm flat on
   Kraken, and write it down as a finding** (the position is then protected only while the
   bot runs).
3. **Kill switch with a position open.** `/kill` + code. Expected: Freqtrade `paused`; the
   position **stays open and is still managed** (a paused bot still exits on its stop/exit
   signal). On Kraken the position **and its stop order** are untouched (look again at Open
   orders). `/resume <n>` + code.
4. **Optional, and only if you can watch for the next few minutes: the bot-down test.** This is
   the real proof that the stop survives the VPS being down. `scripts/compose.sh stop freqtrade`
   (Conductor will report it unreachable; that is expected). On Kraken, Open orders **still
   shows the same stop order**. Then `scripts/compose.sh up -d freqtrade`: Freqtrade boots
   `paused`, Conductor starts it, and the stop order is **the same one** (same trigger price; no
   second order). If a second stop order appears, cancel nothing by hand: `/kill`, `/flatten`,
   and write it down.
5. **Nuclear with a position open.** Only do this while you are happy to close the position now
   (it will realise a small loss or gain). `/flatten` + `yes <code>`. Expected reply lists
   `cancel_order:<id>` (only if an entry/exit order was open; the stop order is cancelled by
   Freqtrade as part of the exit and is not listed), `force_exit_all: ok`, `confirm_flat: ok`,
   `stop: ok`, within about a minute. On Kraken: the position is **sold at market**, the
   order history shows the sell, **Open orders is empty** (the stop order is gone: a stop left
   behind after a sell would be a finding), the coin balance is back to what you wrote down
   in A4 (that is R5 working in reverse). `scripts/drill-check.sh` → `positions: 0`,
   `freqtrade=stopped`. Then `/resume <n>` + code to carry on.
6. **Reconcile one full trade**: Kraken order history vs the dashboard **Positions** page vs
   `scripts/trading-mode.sh cli capital` (`realized_profit` equals the sum of closed trades,
   fees included). Differences are findings, not noise: write them down.
7. **Judge it by plumbing, not profit.** Record the results, with timestamps and what surprised you,
   in `docs/drills/` (copy `TEMPLATE.md`; name it `results-live-pilot-<date>.md`).

If nothing opens within several days, that is the strategy being quiet, not a fault. Decide
deliberately (note it, do not improvise) whether to keep waiting; there is no sanctioned way to
force an entry.

### E5. Daily, for the first week

- Telegram `/status` shows the LIVE banner, `Halts: none` (or what you expect) and
  `Freqtrade primary: running`.
- healthchecks.io is **up**; the 03:15 UTC backup ran (dashboard Monitoring box).
- Kraken Portfolio: USD plus the one position's coin is about $20, minus fees; **no** other
  whitelisted coin has appeared.
- Midnight UTC: the daily fence ran (`$2` cap; with a $20 stake it will almost never trigger).

## Part F — If something goes wrong

- **Anything unexpected with real money:** Telegram `/kill` first. If a position is open and you
  want out: `/flatten`. Then follow [`kill-switch.md`](kill-switch.md) /
  [`nuclear-protocol.md`](nuclear-protocol.md).
- **A halt fired** (daily loss $0.60, drawdown $2.00, 3 losses in a row, capital or position
  cap): that is the system working. Read it (`/halts`), decide, `/resume <id>`.
- **Conductor will not start, `R5 account isolation violated`:** "R5 abort" in
  [`start-stop.md`](start-stop.md).
- **Conductor will not start, `STARTUP REFUSED: Freqtrade has dry_run=...`:** Freqtrade and
  Conductor disagree about the mode. Do not override. `scripts/trading-mode.sh status`; if the
  state is inconsistent, `scripts/trading-mode.sh dry-run` (it refuses if a real position is
  open) and start again from Part D.
- **The VPS is down or being rebuilt while live:** an open position keeps its **stop order on
  Kraken** (check Open orders on Kraken's site from your phone: it should still be there), but
  nothing else is managing it (no exit signals, no halts, no new fills handled). Get the server back; `/flatten`
  needs it, so if you must exit sooner, sell by hand on Kraken's site. Before a *deliberate*
  rebuild, `/flatten` and confirm on Kraken that there are no positions **and no open orders**,
  then follow [`rebuild-vps.md`](rebuild-vps.md), whose "Which mode is this server in?" section
  has the live restore: `restore-test.sh --mode live`, volume `infra_conductor-data-live`,
  trade DB `tradesv3.live.sqlite`, and `scripts/trading-mode.sh live` to bring it back.
- **Key suspected leaked:** revoke it on Kraken **first** (that alone stops it trading), then
  [`key-rotation.md`](key-rotation.md). The key cannot withdraw, and is IP-whitelisted.
- **The dry-run ledger archive** (`archive/dry-run-*.tgz`, mode 600) is the only copy of the soak's
  ledger; copy it off the VPS once. It is never restored into the live volume.

## Part G — End of the pilot

1. Flat: `/flatten` if a position is open; confirm on Kraken.
2. `scripts/trading-mode.sh dry-run` (`make go-dry-run`).
3. Blank the key in `.env`, `make push-env`, **delete the key on Kraken**.
4. Withdraw what you want to keep from Kraken **by hand**, on Kraken's own site (R3: nothing in
   this repo moves money).
5. Write the pilot up in `docs/drills/` and update the roadmap (Phase 4). Do not add money, and do
   not call it "validated" for any strategy: it validated plumbing only (ADR-0019).
