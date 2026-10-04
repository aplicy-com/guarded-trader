# Freqtrade REST fixtures

**Provenance:** `ping`, `show_config`, `status`, `trades` and `profit` were
**recorded on 2026-10-04 from a real local Freqtrade 2026.8 dry-run instance**
(this repo's own `infra/docker-compose.yml`, strategy `Baseline4h`, Kraken,
`dry_run: true`). Nothing secret is in these responses (the endpoints return no
credentials); each file was scanned against every secret value in `.env`
before being committed, with zero hits. The trades are simulated dry-run
trades.

`status_empty.json` (`[]`), `balance.json` and `whitelist.json` are
**hand-written** from the Freqtrade REST documentation's response shapes, NOT
recorded (3A-2 was built without a running Freqtrade instance): re-record them
with the loop below (`/balance`, `/whitelist`) before relying on them for the
live R5 check.

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
