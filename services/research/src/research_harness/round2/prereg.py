"""WP-A: write every round-2 trial to the append-only registry before any of them runs.

    scripts/research-round2.sh prereg     # passes --commit <HEAD>; refuses a dirty spec file

Each trial's registry hash covers the whole frozen spec file (candidates-round2.json), the
trial key, its params, per-fill cost, the data snapshot and the pre-registration commit. The
round-2 runner (WP-C) rebuilds that hash from the registry row and refuses to score a trial
whose spec no longer matches it.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from research_harness.registry import Registry, strategy_hash

SPEC = Path("/repo/services/research/candidates-round2.json")
SNAPSHOT_REPORT = Path("/repo/services/freqtrade/user_data/data/kraken/kraken-archive-report.json")
ENGINE = "none: round-2 daily portfolio engine (research_harness.round2)"


@dataclass(frozen=True, slots=True)
class Trial:
    key: str  # e.g. "R2-01/base/canonical"
    candidate: str
    case: str
    timerange_name: str
    timerange: str
    per_fill: float


def trials(spec: dict) -> list[Trial]:
    out = []
    for cid in spec["candidates"]:
        for t in spec["trials"]["per_candidate"]:
            name = spec["trials"]["full_history_map"][cid] if t["timerange"] == "full_history" else t["timerange"]
            out.append(
                Trial(
                    key=f"{cid}/{t['case']}/{t['timerange']}",
                    candidate=cid,
                    case=t["case"],
                    timerange_name=name,
                    timerange=spec["timeranges"][name]["range"],
                    per_fill=float(spec["cost_cases"][t["case"]]["per_fill"]),
                )
            )
    return out


def engine_tag(commit: str) -> str:
    return f"{ENGINE}; prereg commit {commit}"


def registry_args(spec: dict, spec_bytes: bytes, t: Trial, commit: str) -> dict:
    c = spec["candidates"][t.candidate]
    return dict(
        strategy=t.key,
        family=c["family"],
        hypothesis=c["hypothesis"],
        params=c["params"],
        canonical_timerange=t.timerange,
        fee=t.per_fill,
        data_snapshot_id=spec["data"]["data_snapshot_id"],
        freqtrade_version=engine_tag(commit),
        source=spec_bytes + b"\n" + t.key.encode(),
    )


def expected_hash(args: dict) -> str:
    return strategy_hash(
        args["source"], args["params"], args["fee"], args["data_snapshot_id"], args["freqtrade_version"]
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", required=True, help="git commit that froze candidates-round2.json")
    p.add_argument("--registry", type=Path, default=Path("/state/registry.sqlite"))
    p.add_argument("--spec", type=Path, default=SPEC)
    p.add_argument(
        "--snapshot-report",
        type=Path,
        default=SNAPSHOT_REPORT,
    )
    a = p.parse_args()
    spec_bytes = a.spec.read_bytes()
    spec = json.loads(spec_bytes)
    on_disk = json.loads(a.snapshot_report.read_text())["data_snapshot_id"]
    if on_disk != spec["data"]["data_snapshot_id"]:
        raise SystemExit(f"data snapshot {on_disk} != frozen {spec['data']['data_snapshot_id']}")
    reg = Registry(a.registry)
    before = reg.n_trials()
    rows = []
    for t in trials(spec):
        args = registry_args(spec, spec_bytes, t, a.commit)
        trial_id = reg.preregister(**args)
        rows.append(
            {
                "trial": t.key,
                "trial_id": trial_id,
                "strategy_hash": expected_hash(args),
                "per_fill": t.per_fill,
                "timerange": t.timerange,
            }
        )
    print(json.dumps({"n_before": before, "n_after": reg.n_trials(), "commit": a.commit, "trials": rows}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
