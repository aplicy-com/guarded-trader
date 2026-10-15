# Runbook — Refresh backtest data from Kraken's archive

**When to use:** once after a fresh checkout (no `services/freqtrade/user_data/data/kraken/`
yet), and once per quarter when Kraken publishes a new quarterly incremental (ADR-0020).

**Where:** your Mac, in the repo root. Not on the VPS: backtests and research do not run there,
and the download is ~10 GB.

**What it touches:** only `services/freqtrade/user_data/data/` (git-ignored). Nothing about
trading, dry-run or live changes. No API key is used.

**Before you start:** Docker Desktop is running; at least 25 GB of free disk.

## Steps

1. Check for a new quarterly file. Open
   <https://support.kraken.com/hc/en-us/articles/360047124832-Downloadable-historical-OHLCVT-Open-High-Low-Close-Volume-Trades-data>
   and look at the "Quarterly incremental" list.
   - Nothing newer than the last entry under `incrementals` in
     `scripts/kraken_archive_checksums.json`, and the data already exists: **stop, nothing to do.**
   - A new quarter (e.g. `Kraken_OHLCVT_2026Q4.zip`): continue at step 2.
   - First time on this machine: skip to step 4.

2. Get the new file's hash. In the terminal:
   ```
   curl -sSO --output-dir services/freqtrade/user_data/data/kraken-archive \
     https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_2026Q4.zip
   shasum -a 256 services/freqtrade/user_data/data/kraken-archive/Kraken_OHLCVT_2026Q4.zip
   ```
   Expected: one line, a 64-character hex string, then the file path.

3. Add that file name and hash under `incrementals` in `scripts/kraken_archive_checksums.json`.
   If Kraken also published a new full archive (new `OHLCVT_Full_PARTS_SHA256SUMS.txt` or a new
   full-zip hash on the support page), replace `full_parts` and `full_zip_sha256` with the new
   published values and set `verified_utc` to today. Commit this file on its own branch
   (`chore(data): pin Kraken OHLCVT 2026Q4`).

4. Download and verify:
   ```
   make kraken-data
   ```
   Expected, in order: `download complete; run verify next`, then one `OK` line per part, one
   `OK   Kraken_OHLCVT_Full.zip (reassembled, streamed)`, one `OK` per incremental,
   `all checksums match`, then twelve `OK   <PAIR> <4h|1d>: ... candles ...` lines and
   `data_snapshot_id <16 hex characters>`.
   - Any `FAIL` line in the checksum part: **stop.** Do not convert. Delete the failing file and
     run `make kraken-data` again (it re-downloads). Two failures in a row: Kraken has changed the
     file; read the support page for a new release and go back to step 3.
   - Any `FAIL <PAIR> ...` line in the convert part: **stop.** The message says what is wrong
     (off-grid timestamps, bad OHLC, or two archives disagreeing). Do not use the data; open an
     issue with the message.

5. Optional cross-check against Binance data, if you have it on disk:
   ```
   make kraken-crossval
   ```
   Expected: a JSON list, one entry per pair, with `median_abs_dev_pct` well under 0.1 and
   `share_over_0.5pct` under 0.01. Much larger numbers: write them down and open an issue
   before using the data.

6. Note the new `data_snapshot_id` from step 4. Every research run from now on records it.
   A changed snapshot id means a re-run of an existing candidate is a **new trial** in the
   registry, which is correct: it ran on different data.

7. Optional: free ~10 GB by deleting `services/freqtrade/user_data/data/kraken-archive/`. The
   converted files in `data/kraken/` are all the backtests need. You will download again next
   quarter.
