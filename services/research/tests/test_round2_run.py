"""Runner smoke test on a synthetic market (never the real data: that is WP-C's scored run)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research_harness.registry import Registry
from research_harness.round2 import engine as eng
from research_harness.round2 import prereg, run
from research_harness.round2 import strategies as st

SPEC_PATH = Path(__file__).resolve().parents[1] / "candidates-round2.json"


def synthetic_market() -> eng.Market:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2019-06-01", "2023-12-31", freq="D", tz="UTC")
    n = len(dates)
    regime = np.where((np.arange(n) // 200) % 2 == 0, 0.003, -0.002)
    btc = 100 * np.exp(np.cumsum(regime + rng.normal(0, 0.03, n)))
    eth = 50 * np.exp(np.cumsum(regime * 1.2 + rng.normal(0, 0.04, n)))
    op = {st.BTC: np.r_[btc[0], btc[:-1]], st.ETH: np.r_[eth[0], eth[:-1]]}
    return eng.Market(dates, op, {st.BTC: btc, st.ETH: eth})


def test_scorer_produces_gate1_and_round2_fields_and_finalise_records_results(tmp_path):
    spec_bytes = SPEC_PATH.read_bytes()
    spec = json.loads(spec_bytes)
    m = synthetic_market()
    reports = {}
    for cid in spec["candidates"]:
        for tr_name, rng_str in (("canonical", "20210101-20231001"), ("full_history", "20200901-20231001")):
            t = prereg.Trial(f"{cid}/base/{tr_name}", cid, "base", tr_name, rng_str, 0.009)
            reports[t.key] = run.Scorer(m, spec, t, seeds=2).score()
    r = reports["R2-01/base/canonical"]
    assert r["walk_forward"]["rolling"]["n_windows"] == 7  # 2022Q1..2023Q3
    assert r["null"]["verdict"]["seeds"] == 2 and r["matched_null"]["seeds"] == 2
    assert r["benchmark_btc_buy_hold"]["net_return"] != 0
    assert set(r["min_order"]) == {"cad35", "usd100", "thresholds_usd"}
    # R2-03 is always in: its only trade is the force exit, so Gate 1's headline is empty.
    assert reports["R2-03/base/canonical"]["full"]["n_trades"] == 0

    reg = Registry(tmp_path / "r.sqlite")
    ids = {}
    for key in reports:
        cid = key.split("/")[0]
        c = spec["candidates"][cid]
        ids[key] = reg.preregister(
            strategy=key,
            family=c["family"],
            hypothesis=c["hypothesis"],
            params=c["params"],
            canonical_timerange="x",
            fee=0.009,
            data_snapshot_id="s",
            freqtrade_version="t",
            source=key.encode(),
        )
    summary = run.finalise(spec, reports, reg, ids)
    assert summary["n_trials"] == 8
    assert set(summary["verdicts"]) == {"R2-01", "R2-02", "R2-03", "R2-04"}
    for v in summary["verdicts"].values():
        # >= 100 closed trades is impossible at this turnover: Gate 1 fails by construction.
        assert v["checks"]["gate1_canonical_base"] is False and v["passes_round2"] is False
    assert all(rep["gate1"]["checks"]["min_trades_canonical_ge_100"] is False for rep in reports.values())
    assert all(row["sharpe_daily"] is not None for row in reg.rows())
