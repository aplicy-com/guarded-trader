"""WP-A data coverage check: missing daily candles per pair and range (STOP if > 5 %)."""

from __future__ import annotations

import json

import pandas as pd

from research_harness.round2.data import PAIRS, REPORT, load_daily

STOP_FRACTION = 0.05
# Warm-up starts: the 200-day SMA and 365-day return need history before the scored range.
RANGES = {
    "BTC/USD": [("2014-01-01", "2026-09-30"), ("2015-01-01", "2026-09-30"), ("2021-01-01", "2026-09-30")],
    "ETH/USD": [("2015-08-07", "2026-09-30"), ("2016-09-01", "2026-09-30"), ("2021-01-01", "2026-09-30")],
}


def main() -> int:
    report = json.loads(REPORT.read_text())
    out = {"data_snapshot_id": report["data_snapshot_id"], "series": {}}
    worst = 0.0
    for pair in PAIRS:
        raw = load_daily(pair)
        rows = []
        for a, b in RANGES[pair]:
            days = pd.date_range(a, b, freq="D", tz="UTC")
            present = raw.index.intersection(days)
            missing = days.difference(present)
            frac = len(missing) / len(days)
            worst = max(worst, frac)
            rows.append(
                {
                    "range": f"{a} -> {b}",
                    "expected_days": len(days),
                    "missing_days": len(missing),
                    "missing_fraction": round(frac, 5),
                    "missing_dates": [str(d.date()) for d in missing],
                    "zero_volume_days": int((raw.loc[present, "volume"] <= 0).sum()),
                }
            )
        out["series"][pair] = {
            "first": str(raw.index[0].date()),
            "last": str(raw.index[-1].date()),
            "rows": len(raw),
            "feather_sha256": report["series"][f"{pair} 1d"]["feather_sha256"],
            "ranges": rows,
        }
    out["worst_missing_fraction"] = worst
    out["stop"] = worst > STOP_FRACTION
    print(json.dumps(out, indent=1))
    return 3 if out["stop"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
