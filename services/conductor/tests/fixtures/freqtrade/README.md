# Freqtrade REST fixtures

**Provenance:** `ping`, `show_config`, `status`, `trades` and `profit` were
**recorded on 2026-10-04 from a real local Freqtrade 2026.8 dry-run instance**
(this repo's own `infra/docker-compose.yml`, strategy `Baseline4h`, Kraken,
`dry_run: true`). Nothing secret is in these responses (the endpoints return no
credentials); each file was scanned against every secret value in `.env`
before being committed, with zero hits. The trades are simulated dry-run
trades.

`balance.json` and `whitelist.json` were **recorded on 2026-10-04 from the VPS
dry-run Freqtrade** (read-only GETs run inside the container so credentials
never left the host; nothing secret in the responses). Caveat: a dry-run
`/balance` shows simulated wallets only; re-record it from a live-mode instance
before relying on it for the real R5 check.

`status_empty.json` (`[]`) is hand-written: the "no open positions" case.

Real-data quirks the contract tests now cover: `max_open_trades` arrives as
`3.0`, timestamps carry milliseconds, `/trades` returns closed trades only,
and money values are JSON floats (parsed via `Decimal`).

## Re-recording

With the stack up (`make up`) and credentials in `.env`:

    set -a; . ./.env; set +a
    for ep in ping show_config status profit balance whitelist; do
      curl -s -u "$FREQTRADE__API_SERVER__USERNAME:$FREQTRADE__API_SERVER__PASSWORD" \
        http://127.0.0.1:8080/api/v1/$ep | python3 -m json.tool --sort-keys > $ep.json
    done
    curl -s -u "$FREQTRADE__API_SERVER__USERNAME:$FREQTRADE__API_SERVER__PASSWORD" \
      "http://127.0.0.1:8080/api/v1/trades?limit=50" | python3 -m json.tool --sort-keys > trades.json

Then grep the files for every secret value in `.env`, update the expected
numbers in `tests/test_freqtrade_client.py`, and run `make conductor-test`.
A failure after a Freqtrade upgrade means the API drifted from what the
client expects.
