import json
from pathlib import Path

from research_harness.registry import Registry
from research_harness.round2 import prereg

SPEC_PATH = Path(__file__).resolve().parents[1] / "candidates-round2.json"


def test_frozen_spec_has_twenty_trials_with_unique_keys_and_gate1_cost_basis():
    spec = json.loads(SPEC_PATH.read_text())
    ts = prereg.trials(spec)
    assert len(ts) == 20
    assert len({t.key for t in ts}) == 20
    base = [t for t in ts if t.case == "base" and t.timerange_name == "canonical"]
    assert {t.candidate for t in base} == {"R2-01", "R2-02", "R2-03", "R2-04"}
    assert all(t.per_fill == 0.009 and t.timerange == "20220101-20261001" for t in base)
    # Gate 1's canonical range and cost basis are the round-1 ones, unchanged.
    r1 = json.loads((SPEC_PATH.parent / "candidates.json").read_text())
    assert spec["timeranges"]["canonical"]["range"] == r1["canonical_timerange"]
    costs = json.loads((SPEC_PATH.parents[1] / "freqtrade/user_data/config.backtest-costs.json").read_text())
    assert spec["cost_cases"]["base"]["per_fill"] == costs["fee"]
    for c in spec["candidates"].values():
        assert len(c["params"]) <= 6


def test_preregistration_is_idempotent_and_hash_is_reproducible(tmp_path):
    spec_bytes = SPEC_PATH.read_bytes()
    spec = json.loads(spec_bytes)
    reg = Registry(tmp_path / "r.sqlite")
    t = prereg.trials(spec)[0]
    args = prereg.registry_args(spec, spec_bytes, t, "abc123")
    first = reg.preregister(**args)
    assert reg.preregister(**args) == first  # unscored: resumes the same trial, N unchanged
    assert reg.n_trials() == 1
    row = reg.rows()[0]
    assert row["strategy_hash"] == prereg.expected_hash(args)
    assert row["freqtrade_version"].endswith("prereg commit abc123")
    edited = prereg.registry_args(spec, spec_bytes + b" ", t, "abc123")
    assert prereg.expected_hash(edited) != row["strategy_hash"]  # any spec edit is detectable
