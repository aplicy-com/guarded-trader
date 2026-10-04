# Freqtrade REST fixtures

**Provenance: hand-built from the Freqtrade 2026.8 REST API schema, NOT recorded
from a live instance** (no Freqtrade was running when 3A-1 was written, and the
dry-run host is the VPS/Mac, not the dev environment). Values are illustrative;
the field names and types are what the contract test pins.

Replace with real recordings before 3A-2 relies on them, on a machine where the
dry-run bot is up (scrub nothing secret: these endpoints return no credentials):

    for ep in ping show_config status profit; do
      curl -s -u "$USER:$PASS" http://127.0.0.1:8080/api/v1/$ep | python -m json.tool > $ep.json
    done
    curl -s -u "$USER:$PASS" "http://127.0.0.1:8080/api/v1/trades?limit=50" | python -m json.tool > trades.json

then run `make conductor-test`; a failure means Freqtrade's API drifted from
what the client expects.
