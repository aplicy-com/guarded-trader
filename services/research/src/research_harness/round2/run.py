"""WP-C: score every pre-registered round-2 trial. Sandbox only (scripts/research-round2.sh run).

For each of the 20 trials in candidates-round2.json:

1. find its registry row, rebuild its hash from the frozen spec and refuse to run on a mismatch
   (the spec changed after registration) or if it already has a result;
2. backtest it (engine.simulate) and score it with the harness's own functions: Gate 1 headline
   metrics (metrics.compute_metrics), 2x cost stress, anchored and rolling walk-forward
   (walkforward), the C11 random-entry null (null.verdict), then the round-2 additions: the
   account view, the matched switching null, the turnover cap and the minimum-order check;
3. record every result in the registry, then compute DSR against the final N and Sharpe
   dispersion (all rounds), evaluate Gate 1 with research_harness.cli.gate1, and write
   /out/<trial>.json and /out/summary.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from research_harness import cli, dsr, metrics, null, walkforward
from research_harness.registry import Registry
from research_harness.round2 import data, prereg
from research_harness.round2 import engine as eng
from research_harness.round2 import strategies as st

log = logging.getLogger("round2")

TURNOVER_CAP = 4.0
MIN_ORDER_HEADROOM = 1.2
MATCHED_SEED_BASE = 2_000_000
_MARKET: eng.Market | None = None


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def account(equity: pd.Series, balance: float) -> dict:
    """The whole account, final open position included (closed at the last close with costs)."""
    years = max((equity.index[-1] - equity.index[0]).days + 1, 1) / metrics.DAYS_PER_YEAR
    final = float(equity.iloc[-1])
    return {
        "net_return": final / balance - 1,
        "cagr": (final / balance) ** (1 / years) - 1 if final > 0 else -1.0,
        "sharpe_daily": metrics.sharpe(equity.pct_change().dropna()),
        "max_drawdown": metrics.max_drawdown(equity),
        "final_equity": final,
    }


class Scorer:
    def __init__(self, m: eng.Market, spec: dict, trial: prereg.Trial, seeds: int) -> None:
        self.m, self.spec, self.t, self.seeds = m, spec, trial, seeds
        self.cand = spec["candidates"][trial.candidate]
        self.c = st.build(trial.candidate, m, self.cand["params"])
        self.balance = float(spec["start_balance"]["base"]["usd"])
        a, b = trial.timerange.split("-")
        self.start_ts, self.end_ts = _ts(a), _ts(b)  # end exclusive
        self.closes = m.closes_frame()

    def idx(self, ts: pd.Timestamp) -> int:
        return int(self.m.dates.searchsorted(ts))

    def sim(self, start: pd.Timestamp, end: pd.Timestamp, cost: float, decide=None) -> eng.SimResult:
        return eng.simulate(
            self.m,
            decide or st.rule_decide(self.c),
            self.c.is_check_day,
            self.idx(start),
            self.idx(end),
            cost,
            self.balance,
        )

    def headline(self, res: eng.SimResult, start: pd.Timestamp, end: pd.Timestamp):
        last = self.m.dates[res.end - 1]
        return metrics.compute_metrics(res.trades, self.closes, start, last, self.balance)

    def score(self) -> dict:
        t0 = time.time()
        cost, s, e = self.t.per_fill, self.start_ts, self.end_ts
        base = self.sim(s, e, cost)
        m_full, rets_full = self.headline(base, s, e)
        eq = base.equity_series(self.m.dates)
        r: dict = {
            "trial": self.t.key,
            "candidate": self.t.candidate,
            "case": self.t.case,
            "timerange": self.t.timerange,
            "per_fill": cost,
            "spec": {"params": self.cand["params"], "name": self.cand["name"], "rule": self.cand["rule"]},
            "full": m_full.as_dict(),
            "account": account(eq, self.balance),
            "fills": len(base.fills),
            "closed_trades_incl_force_exit": len(base.trades),
            "first_last_day": [str(self.m.dates[base.start].date()), str(self.m.dates[base.end - 1].date())],
        }
        r["full"]["exit_reasons"] = pd.Series([x["exit_reason"] for x in base.trades]).value_counts().to_dict()
        r["trades"] = [
            {k: x[k] for k in ("pair", "open_date", "close_date", "exit_reason", "profit_abs")}
            | {"orders": len(x["orders"])}
            for x in base.trades
        ]

        # benchmark: BTC buy-and-hold at the same cost, and the harness's fee-free figure
        bh = eng.simulate(
            self.m,
            lambda i, h, w: None,
            lambda i: False,
            base.start,
            base.end,
            cost,
            self.balance,
            initial_target={st.BTC: 1.0},
        )
        r["benchmark_btc_buy_hold"] = account(bh.equity_series(self.m.dates), self.balance)
        r["benchmark_btc_buy_hold_fee_free"] = metrics.buy_and_hold(self.closes[st.BTC], s, self.m.dates[base.end - 1])

        # 2x cost stress (ADR-0021, reported)
        stress = self.sim(s, e, 2 * cost)
        m2, _ = self.headline(stress, s, e)
        r["cost_stress_2x"] = {
            "fee": 2 * cost,
            **m2.as_dict(),
            "account": account(stress.equity_series(self.m.dates), self.balance),
        }

        # walk-forward, OOS windows shared by both schemes
        oos_cache: dict[str, tuple] = {}
        r["walk_forward"] = {}
        for scheme in ("anchored", "rolling"):
            rows, oos_rets = [], []
            for w in walkforward.windows(s, e, scheme):
                m_is, _ = self.headline(self.sim(w.is_start, w.is_end, cost), w.is_start, w.is_end)
                key = cli.tr(w.oos_start, w.oos_end)
                if key not in oos_cache:
                    oos_cache[key] = self.headline(self.sim(w.oos_start, w.oos_end, cost), w.oos_start, w.oos_end)
                m_oos, r_oos = oos_cache[key]
                oos_rets.append(r_oos)
                rows.append(
                    {
                        "is": cli.tr(w.is_start, w.is_end),
                        "oos": key,
                        "is_sharpe": m_is.sharpe_daily,
                        "oos_sharpe": m_oos.sharpe_daily,
                        "oos_trades": m_oos.n_trades,
                        "oos_net_profit": m_oos.net_profit,
                        "oos_max_drawdown": m_oos.max_drawdown,
                    }
                )
            r["walk_forward"][scheme] = asdict(walkforward.summarise(scheme, rows, oos_rets))

        r["null"] = self.c11(base)
        r["matched_null"] = self.matched(base, r["account"]["sharpe_daily"])

        rt = eng.round_trips_per_year(base.fills, self.m.dates)
        years = range(self.m.dates[base.start].year, self.m.dates[base.end - 1].year + 1)
        r["turnover"] = {
            "round_trips_per_year": {y: rt.get(y, 0.0) for y in years},
            "max_round_trips_in_a_year": max(rt.values(), default=0.0),
            "closed_trades_per_year": {
                y: sum(1 for x in base.trades if x["exit_reason"] != eng.FORCE_EXIT and _ts(x["close_date"]).year == y)
                for y in years
            },
            "cap": TURNOVER_CAP,
        }
        r["turnover"]["passes_cap"] = r["turnover"]["max_round_trips_in_a_year"] <= TURNOVER_CAP
        r["min_order"] = self.min_order(base)
        r["_rets_full"] = [float(x) for x in rets_full.to_numpy()]
        r["elapsed_s"] = round(time.time() - t0, 1)
        return r

    # --- C11 random-entry null (ADR-0021), calibrated as research_harness.cli does it -----------
    def c11(self, base: eng.SimResult) -> dict:
        cost, s, e = self.t.per_fill, self.start_ts, self.end_ts
        rates = st.c11_rates(self.c, base.decisions, base.trades)

        def row(seed: int, rates_: dict[str, float]) -> dict:
            entry = st.c11_entry(self.c, self.m, rates_, seed, base.start, base.end)
            res = self.sim(s, e, cost, st.rule_decide(self.c, entry))
            return self.headline(res, s, e)[0].as_dict()

        target = len(base.trades)
        scale, calibration = 1.0, []
        seed_iter = iter(range(cli.NULL_PILOT_SEEDS * cli.NULL_CALIBRATION_ROUNDS))
        for _ in range(cli.NULL_CALIBRATION_ROUNDS):
            used = {p: min(x * scale, 1.0) for p, x in rates.items()}
            pilot = [row(next(seed_iter), used) for _ in range(cli.NULL_PILOT_SEEDS // cli.NULL_CALIBRATION_ROUNDS)]
            mean_n = float(np.mean([p["n_trades"] + p["n_force_exit"] for p in pilot]))
            calibration.append({"scale": scale, "mean_null_trades": mean_n})
            if mean_n <= 0 or target == 0 or abs(mean_n / target - 1) <= 0.10:
                break
            scale *= target / mean_n
        scaled = {p: min(x * scale, 1.0) for p, x in rates.items()}
        nulls = [row(cli.NULL_SEED_BASE + k, scaled) for k in range(self.seeds)]
        full = self.headline(base, s, e)[0].as_dict()
        return {
            "rates_initial": rates,
            "calibration": calibration,
            "rate_scale": scale,
            "rates_used": scaled,
            "candidate_trades_incl_force_exit": target,
            "null_mean_trades_incl_force_exit": float(np.mean([n["n_trades"] + n["n_force_exit"] for n in nulls])),
            "verdict": null.verdict(full, nulls).as_dict(),
            "null_sharpe_quantiles": np.percentile([n["sharpe_daily"] for n in nulls], [5, 25, 50, 75, 95]).tolist(),
            "null_mdd_quantiles": np.percentile([n["max_drawdown"] for n in nulls], [5, 25, 50, 75, 95]).tolist(),
        }

    # --- matched switching null (round-2 requirement), account view -----------------------------
    def matched(self, base: eng.SimResult, cand_sharpe: float) -> dict:
        cost, s, e = self.t.per_fill, self.start_ts, self.end_ts
        days = sorted(base.decisions)
        states = [base.decisions[d] for d in days]
        sharpes, mdds, rets = [], [], []
        entry_days = [d for d in days if base.decisions[d] is not None]
        for k in range(self.seeds):
            rng = np.random.default_rng(MATCHED_SEED_BASE + k)
            if self.c.always_in and entry_days:
                d0 = min(entry_days)
                pair = base.decisions[d0]
                w0 = base.targets[d0][pair]
                later = [base.targets[d][pair] for d in sorted(base.targets) if d > d0 and pair in base.targets[d]]
                sched = st.matched_vol_schedule(days, d0, later, rng)
                decide = st.schedule_decide(pair, d0, w0, sched)
            else:
                path = dict(zip(days, st.matched_states(states, self.c.pairs, rng), strict=True))
                decide = st.path_decide(self.c, path)
            res = self.sim(s, e, cost, decide)
            acc = account(res.equity_series(self.m.dates), self.balance)
            sharpes.append(acc["sharpe_daily"])
            mdds.append(acc["max_drawdown"])
            rets.append(acc["net_return"])
        p95 = float(np.percentile(sharpes, 95))
        return {
            "seeds": self.seeds,
            "basis": "account view",
            "candidate_sharpe": cand_sharpe,
            "null_sharpe_p95": p95,
            "null_sharpe_quantiles": np.percentile(sharpes, [5, 25, 50, 75, 95]).tolist(),
            "null_mdd_median": float(np.median(mdds)),
            "null_net_return_median": float(np.median(rets)),
            "candidate_sharpe_percentile": float((np.array(sharpes) < cand_sharpe).mean() * 100),
            "in_out_switches": max(len(st.runs(states)) - 1, 0),
            "check_periods_in_market": sum(x is not None for x in states),
            "check_periods_total": len(states),
            "passes": bool(cand_sharpe > p95),
        }

    def min_order(self, base: eng.SimResult) -> dict:
        mins = self.spec["min_order_check"]["kraken_minimums_2026_11_01"]
        out = {}
        for label, bal in (
            ("cad35", self.balance),
            ("usd100", float(self.spec["start_balance"]["sensitivity"]["usd"])),
        ):
            sizes, fails = [], 0
            for f in base.fills:
                if f.force_exit:
                    continue
                k = mins[f.pair]
                thr = MIN_ORDER_HEADROOM * max(k["costmin"], k["ordermin"] * k["last_mid"])
                size = f.turnover * bal
                sizes.append(size)
                fails += size < thr
            out[label] = {
                "start_usd": bal,
                "fills_checked": len(sizes),
                "fills_below_120pct_min": int(fails),
                "smallest_fill_usd": min(sizes) if sizes else None,
                "passes": fails == 0,
            }
        out["thresholds_usd"] = {
            p: MIN_ORDER_HEADROOM * max(k["costmin"], k["ordermin"] * k["last_mid"]) for p, k in mins.items()
        }
        return out


def _init(datadir: str) -> None:
    global _MARKET
    _MARKET = eng.Market.from_panel(data.panel(Path(datadir)))


def _score(args: tuple) -> dict:
    spec, trial, seeds = args
    assert _MARKET is not None
    return Scorer(_MARKET, spec, trial, seeds).score()


def verify_recorded(reports: dict[str, dict], reg: Registry, ids: dict[str, str]) -> None:
    """--recompute: the recorded Gate 1 headline must be reproduced exactly, or nothing is written."""
    recorded = {row["trial_id"]: row for row in reg.rows()}
    for key, r in reports.items():
        row = recorded[ids[key]]
        if (
            row["sharpe_daily"] != r["full"]["sharpe_daily"]
            or row["n_trades"] != r["full"]["n_trades"]
            or json.loads(row["daily_returns_json"]) != r["_rets_full"]
        ):
            raise SystemExit(f"{key}: recomputed headline differs from the recorded result; refusing")


def finalise(spec: dict, reports: dict[str, dict], reg: Registry, ids: dict[str, str], record: bool = True) -> dict:
    """Record results, then DSR against the final N, Gate 1 and the round-2 verdict."""
    for key, r in reports.items():
        if not record:
            break
        rets = np.array(r["_rets_full"])
        sd = rets.std(ddof=1) if len(rets) > 1 else 0.0
        reg.record_result(
            ids[key],
            sharpe_daily=r["full"]["sharpe_daily"],
            sharpe_period=float(rets.mean() / sd) if sd > 0 else 0.0,
            n_trades=r["full"]["n_trades"],
            metrics=r["full"],
            daily_returns=r["_rets_full"],
        )
    n, sigma = reg.n_trials(), reg.sigma_trials()
    for key, r in reports.items():
        r["trial_id"] = ids[key]
        r["dsr"] = dsr.deflated_sharpe(np.array(r.pop("_rets_full")), n, sigma).as_dict()
        r["gate1"] = cli.gate1(r)
    verdicts = {}
    for cid in spec["candidates"]:
        b = reports[f"{cid}/base/canonical"]
        fh = reports[f"{cid}/base/full_history"]
        checks = {
            "gate1_canonical_base": b["gate1"]["passes"],
            "turnover_cap_canonical_base": b["turnover"]["passes_cap"],
            "turnover_cap_full_history_base": fh["turnover"]["passes_cap"],
            "beats_matched_null_canonical_base": b["matched_null"]["passes"],
            "min_order_cad35_canonical_base": b["min_order"]["cad35"]["passes"],
        }
        verdicts[cid] = {"checks": checks, "passes_round2": all(checks.values())}
    return {"n_trials": n, "sigma_trials_period": sigma, "verdicts": verdicts}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stderr)
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=200)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--registry", type=Path, default=Path("/state/registry.sqlite"))
    p.add_argument("--spec", type=Path, default=prereg.SPEC)
    p.add_argument("--datadir", type=Path, default=data.DATADIR)
    p.add_argument("--out", type=Path, default=Path("/out"))
    p.add_argument(
        "--recompute",
        action="store_true",
        help="rebuild reports of already-scored trials without writing to the registry; refuses unless "
        "each trial's recorded Sharpe, trade count and daily returns are reproduced exactly",
    )
    a = p.parse_args()
    spec_bytes = a.spec.read_bytes()
    spec = json.loads(spec_bytes)
    reg = Registry(a.registry)
    rows = {row["strategy"]: row for row in reg.rows()}
    trials = prereg.trials(spec)
    ids: dict[str, str] = {}
    for t in trials:
        row = rows.get(t.key)
        if row is None:
            raise SystemExit(f"{t.key} was never pre-registered")
        commit = row["freqtrade_version"].rsplit("prereg commit ", 1)[1]
        args = prereg.registry_args(spec, spec_bytes, t, commit)
        if prereg.expected_hash(args) != row["strategy_hash"]:
            raise SystemExit(f"{t.key}: frozen spec changed since registration; refusing to score")
        if a.recompute:
            if row["sharpe_daily"] is None:
                raise SystemExit(f"{t.key}: --recompute needs a scored trial")
            ids[t.key] = row["trial_id"]
            continue
        if row["sharpe_daily"] is not None:
            raise SystemExit(f"{t.key}: already scored; re-running cannot reset N")
        ids[t.key] = reg.preregister(**args)  # unscored: returns the same trial id
        assert ids[t.key] == row["trial_id"]
    log.info("verified %d pre-registered trials; N=%d", len(ids), reg.n_trials())

    t0 = time.time()
    jobs = [(spec, t, a.seeds) for t in trials]
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(str(a.datadir),)) as ex:
            done = list(ex.map(_score, jobs))
    else:
        _init(str(a.datadir))
        done = [_score(j) for j in jobs]
    reports = {r["trial"]: r for r in done}
    if a.recompute:
        verify_recorded(reports, reg, ids)
    summary = finalise(spec, reports, reg, ids, record=not a.recompute)
    summary["recomputed_without_recording"] = a.recompute
    summary["elapsed_s"] = round(time.time() - t0, 1)
    summary["seeds"] = a.seeds
    a.out.mkdir(parents=True, exist_ok=True)
    for key, r in reports.items():
        (a.out / f"{key.replace('/', '__')}.json").write_text(json.dumps(r, indent=1, default=_json_default))
    summary["trials"] = {
        key: {
            "trial_id": r["trial_id"],
            "account": r["account"],
            "benchmark_btc_buy_hold": r["benchmark_btc_buy_hold"],
            "gate1": r["gate1"],
            "turnover": r["turnover"],
            "matched_null": r["matched_null"],
            "c11": r["null"]["verdict"],
            "min_order": r["min_order"],
            "dsr": r["dsr"]["dsr"],
            "full": {
                k: r["full"][k] for k in ("n_trades", "n_force_exit", "sharpe_daily", "max_drawdown", "fee_ratio")
            },
            "walk_forward": {
                s: {k: v for k, v in w.items() if k != "per_window"} for s, w in r["walk_forward"].items()
            },
            "cost_stress_2x_account": r["cost_stress_2x"]["account"],
        }
        for key, r in reports.items()
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1, default=_json_default))
    log.info("done in %.0fs: %s", summary["elapsed_s"], {c: v["passes_round2"] for c, v in summary["verdicts"].items()})
    return 0


def _json_default(o):
    if isinstance(o, float) and math.isinf(o):
        return "inf"
    if isinstance(o, np.bool_):
        return bool(o)
    return cli._json_default(o)


if __name__ == "__main__":
    raise SystemExit(main())
