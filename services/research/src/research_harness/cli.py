"""Research harness entry point. Runs inside the sandbox only (scripts/research-harness.sh).

    python -m research_harness.cli run <Strategy> [--seeds 200] [--no-register]

For one pre-registered candidate (services/research/candidates.json) on the canonical timerange:

1. pre-register the trial (registry row written before any backtest);
2. full-range backtest at the configured fee (config.backtest-costs.json);
3. the same at 2x that fee (cost stress, reported);
4. anchored and rolling walk-forward (walkforward.py protocol);
5. random-entry null, ``--seeds`` seeds at the candidate's entry rate (C11);
6. record the result, then Deflated Sharpe against the registry's N and sigma;
7. evaluate Gate 1 (docs/08-paper-exit-criteria.md, ADR-0021) and write <out>/<Strategy>.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from research_harness import dsr, metrics, null, walkforward
from research_harness.registry import Registry, strategy_hash

REPO = Path("/repo")
STATE = Path("/state")
OUT = Path("/out")

IS_SHARPE_FLOOR = 1.0
OOS_OVER_IS_FLOOR = 0.5
MIN_TRADES_CANONICAL = 100
FEE_RATIO_CEILING = 0.40
SINGLE_TRADE_CEILING = 0.30
MAX_PARAMS = 6
NULL_PILOT_SEEDS = 24  # split evenly over the calibration rounds
NULL_CALIBRATION_ROUNDS = 4
NULL_SEED_BASE = 1_000_000  # pilot seeds and scored seeds never overlap

log = logging.getLogger("harness")


def tr(start: pd.Timestamp, end: pd.Timestamp) -> str:
    return f"{start:%Y%m%d}-{end:%Y%m%d}"


def parse_tr(s: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    a, b = s.split("-")
    return pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")


class Harness:
    def __init__(self, strategy: str, spec: dict, canonical: str) -> None:
        from research_harness import ft_runner

        self.ft = ft_runner
        ft_runner.install_offline_markets(REPO / "services/research/fixtures/kraken-markets.json")
        ud = Path("/tmp/user_data")
        for sub in ("data", "strategies", "backtest_results", "logs"):
            (ud / sub).mkdir(parents=True, exist_ok=True)
        user_data = REPO / "services/freqtrade/user_data"
        strategy_dir = Path(spec["files"][0]).parent
        self.paths = ft_runner.Paths(
            configs=[user_data / "config.dry_run.json", user_data / "config.backtest-costs.json"],
            strategy_path=REPO / strategy_dir,
            datadir=user_data / "data/kraken",
            user_data_dir=ud,
        )
        self.strategy = strategy
        self.spec = spec
        self.timeframe = spec["timeframe"]
        self.canonical = canonical
        self._closes: pd.DataFrame | None = None

    def session(self, timerange: str, fee: float | None = None):
        return self.ft.Session(self.paths, self.strategy, self.timeframe, timerange, fee)

    def closes(self, session) -> pd.DataFrame:
        if self._closes is None:
            self._closes = metrics.daily_closes(session.ohlcv())
        return self._closes

    def score(self, session, result, start: pd.Timestamp, end: pd.Timestamp):
        m, rets = metrics.compute_metrics(
            result.trades, self.closes(session), start, end - pd.Timedelta(days=1), result.starting_balance
        )
        return m, rets


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stderr)
    for noisy in ("freqtrade", "numexpr"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cands = json.loads((REPO / "services/research/candidates.json").read_text())
    spec = cands["candidates"][args.strategy]
    canonical = cands["canonical_timerange"]
    c_start, c_end = parse_tr(canonical)
    h = Harness(args.strategy, spec, canonical)
    report: dict = {"strategy": args.strategy, "spec": spec, "canonical_timerange": canonical}
    t0 = time.time()

    data_report = json.loads((REPO / "services/freqtrade/user_data/data/kraken/kraken-archive-report.json").read_text())
    snapshot_id = data_report["data_snapshot_id"]
    source = b"".join((REPO / f).read_bytes() for f in spec["files"])

    # 1. full canonical range
    full = h.session(canonical)
    fee = full.fee
    recorded = None
    if args.recompute:
        # Report rebuild: the registry is opened read-only and must already hold this exact trial.
        registry = Registry.open_readonly(args.registry)
        digest = strategy_hash(source, spec["params"], fee, snapshot_id, version("freqtrade"))
        recorded = registry.recorded(digest)
        if recorded is None or recorded["sharpe_daily"] is None:
            raise SystemExit(f"--recompute: no scored trial with hash {digest[:12]} for {args.strategy}")
    else:
        registry = Registry(Path(":memory:") if args.no_register else args.registry)
    trial_id = recorded["trial_id"] if recorded else None
    if not args.no_register and not args.recompute:
        trial_id = registry.preregister(
            strategy=args.strategy,
            family=spec["family"],
            hypothesis=spec["hypothesis"],
            params=spec["params"],
            canonical_timerange=canonical,
            fee=fee,
            data_snapshot_id=snapshot_id,
            freqtrade_version=version("freqtrade"),
            source=source,
        )
    report.update(trial_id=trial_id, fee=fee, data_snapshot_id=snapshot_id, freqtrade_version=version("freqtrade"))
    log.info("trial %s registered; fee %.4f; snapshot %s", trial_id, fee, snapshot_id)

    base = full.run()
    m_full, rets_full = h.score(full, base, c_start, c_end)
    if recorded is not None:
        same = (
            recorded["sharpe_daily"] == m_full.sharpe_daily
            and recorded["n_trades"] == m_full.n_trades
            and json.loads(recorded["daily_returns_json"]) == [float(x) for x in rets_full.to_numpy()]
        )
        if not same:
            raise SystemExit(f"--recompute: {args.strategy} no longer reproduces its recorded result; refusing")
        report["recomputed_without_recording"] = True
        log.info("recompute: recorded headline reproduced exactly for trial %s", trial_id)
    report["full"] = m_full.as_dict()
    report["full"]["freqtrade_final_balance"] = base.final_balance
    report["full"]["backtest_start"] = str(base.start)
    report["full"]["backtest_end"] = str(base.end)
    report["full"]["exit_reasons"] = (
        pd.Series([t["exit_reason"] for t in base.trades]).value_counts().to_dict() if base.trades else {}
    )
    closes = h.closes(full)
    everything = metrics.daily_equity(
        metrics.fills_from_trades(base.trades), closes, c_start, c_end - pd.Timedelta(days=1), base.starting_balance
    )
    # Sanity: the order-level rebuild must land on Freqtrade's own final balance.
    report["full"]["equity_rebuild_minus_freqtrade"] = float(everything.iloc[-1]) - base.final_balance
    report["benchmark_btc_buy_hold"] = metrics.buy_and_hold(closes["BTC/USD"], c_start, c_end - pd.Timedelta(days=1))
    log.info("full: %s", {k: report["full"][k] for k in ("n_trades", "sharpe_daily", "max_drawdown", "net_profit")})

    # 2. cost stress 2x
    stress = h.session(canonical, fee=2 * fee)
    m_stress, _ = h.score(stress, stress.run(), c_start, c_end)
    report["cost_stress_2x"] = {"fee": 2 * fee, **m_stress.as_dict()}

    # 3. walk-forward (OOS windows are shared by both schemes)
    oos_cache: dict[str, tuple] = {}
    report["walk_forward"] = {}
    for scheme in ("anchored", "rolling"):
        rows, oos_rets = [], []
        for w in walkforward.windows(c_start, c_end, scheme):
            is_s = h.session(tr(w.is_start, w.is_end))
            m_is, _ = h.score(is_s, is_s.run(), w.is_start, w.is_end)
            key = tr(w.oos_start, w.oos_end)
            if key not in oos_cache:
                oos_s = h.session(key)
                oos_cache[key] = h.score(oos_s, oos_s.run(), w.oos_start, w.oos_end)
            m_oos, r_oos = oos_cache[key]
            oos_rets.append(r_oos)
            rows.append(
                {
                    "is": tr(w.is_start, w.is_end),
                    "oos": key,
                    "is_sharpe": m_is.sharpe_daily,
                    "oos_sharpe": m_oos.sharpe_daily,
                    "oos_trades": m_oos.n_trades,
                    "oos_net_profit": m_oos.net_profit,
                    "oos_max_drawdown": m_oos.max_drawdown,
                }
            )
        s = walkforward.summarise(scheme, rows, oos_rets)
        report["walk_forward"][scheme] = asdict(s)
        log.info("wf %s: IS %.2f OOS pooled %.2f", scheme, s.is_sharpe_mean, s.oos_sharpe_pooled)

    # 4. random-entry null
    bar = pd.Timedelta(h.timeframe.replace("d", "D"))
    bars = full.bars_in_range()
    rates = null.entry_rates(base.trades, bars, bar)

    exit_fn = full.strategy.populate_exit_trend

    def override(seed: int, rates_: dict[str, float]):
        def populate_entry_trend(df: pd.DataFrame, md: dict) -> pd.DataFrame:
            # Freqtrade ignores an exit signal on a candle that also carries an entry signal, so a
            # random entry on an exit candle would suppress the candidate's own exit. Draw entries
            # only where the candidate's exit is not firing; the candidate never has both either.
            exiting = exit_fn(df.copy(), md).get("exit_long", pd.Series(0, index=df.index)).fillna(0) == 1
            mask = null.entry_mask(md["pair"], df["date"], rates_.get(md["pair"], 0.0), seed)
            df.loc[mask & (df["volume"] > 0).to_numpy() & ~exiting.to_numpy(), "enter_long"] = 1
            return df

        return populate_entry_trend

    def null_row(seed: int, rates_: dict[str, float]) -> dict:
        res = full.run(override(seed, rates_))
        m, _ = h.score(full, res, c_start, c_end)
        return m.as_dict()

    # Calibrate one pooled multiplier so the null's mean trade count matches the candidate's.
    target = len(base.trades)
    scale, calibration = 1.0, []
    seed_iter = iter(range(NULL_PILOT_SEEDS * NULL_CALIBRATION_ROUNDS))
    for _ in range(NULL_CALIBRATION_ROUNDS):
        used = {p: min(r * scale, 1.0) for p, r in rates.items()}
        pilot = [null_row(next(seed_iter), used) for _ in range(NULL_PILOT_SEEDS // NULL_CALIBRATION_ROUNDS)]
        mean_n = float(np.mean([p["n_trades"] + p["n_force_exit"] for p in pilot]))
        calibration.append({"scale": scale, "mean_null_trades": mean_n})
        if mean_n <= 0 or abs(mean_n / target - 1) <= 0.10:
            break
        scale *= target / mean_n
    scaled = {p: min(r * scale, 1.0) for p, r in rates.items()}
    nulls = [null_row(NULL_SEED_BASE + s, scaled) for s in range(args.seeds)]
    v = null.verdict(report["full"], nulls)
    report["null"] = {
        "rates_initial": rates,
        "calibration": calibration,
        "rate_scale": scale,
        "rates_used": scaled,
        "candidate_trades_incl_force_exit": target,
        "null_mean_trades_incl_force_exit": float(np.mean([n["n_trades"] + n["n_force_exit"] for n in nulls])),
        "verdict": v.as_dict(),
        "null_sharpe_quantiles": np.percentile([n["sharpe_daily"] for n in nulls], [5, 25, 50, 75, 95]).tolist(),
        "null_mdd_quantiles": np.percentile([n["max_drawdown"] for n in nulls], [5, 25, 50, 75, 95]).tolist(),
    }
    log.info("null: %s", v.as_dict())

    # 5. record, then deflate against the registry including this trial
    sr_period = float(rets_full.mean() / rets_full.std(ddof=1)) if rets_full.std(ddof=1) > 0 else 0.0
    if trial_id and not args.recompute:
        registry.record_result(
            trial_id,
            sharpe_daily=m_full.sharpe_daily,
            sharpe_period=sr_period,
            n_trades=m_full.n_trades,
            metrics=report["full"],
            daily_returns=[float(x) for x in rets_full.to_numpy()],
        )
    n_trials = registry.n_trials()
    sigma = registry.sigma_trials()
    report["dsr"] = dsr.deflated_sharpe(rets_full.to_numpy(), n_trials, sigma).as_dict()

    # 6. Gate 1
    report["gate1"] = gate1(report)
    report["elapsed_s"] = round(time.time() - t0, 1)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.strategy}.json").write_text(json.dumps(report, indent=1, default=_json_default))
    log.info(
        "gate1 %s; wrote %s in %.0fs",
        report["gate1"]["passes"],
        args.out / f"{args.strategy}.json",
        report["elapsed_s"],
    )
    return 0


def gate1(r: dict) -> dict:
    f = r["full"]
    wf = r["walk_forward"]
    is_ok = f["sharpe_daily"] >= IS_SHARPE_FLOOR
    checks = {
        "params_le_6": len(r["spec"]["params"]) <= MAX_PARAMS,
        "is_sharpe_ge_1": is_ok,
        "wf_both_schemes_ge_8_windows": all(wf[s]["n_windows"] >= walkforward.MIN_OOS_WINDOWS for s in wf),
        "wf_oos_ge_half_is": is_ok
        and all(wf[s]["oos_sharpe_pooled"] >= OOS_OVER_IS_FLOOR * f["sharpe_daily"] for s in wf),
        "min_trades_canonical_ge_100": f["n_trades"] >= MIN_TRADES_CANONICAL,
        "fee_ratio_lt_40pct": f["fee_ratio"] < FEE_RATIO_CEILING,
        "single_trade_le_30pct_net": f["top_trade_share_of_net"] is not None
        and f["top_trade_share_of_net"] <= SINGLE_TRADE_CEILING,
        "force_exit_group_le_30pct_net": f["net_profit"] > 0
        and f["force_exit_profit"] <= SINGLE_TRADE_CEILING * f["net_profit"],
        "beats_random_entry_null": r["null"]["verdict"]["passes"],
    }
    return {
        "checks": checks,
        "passes": all(checks.values()),
        "reported_not_gated": {
            "dsr": r["dsr"]["dsr"],
            "cost_stress_2x_sharpe": r["cost_stress_2x"]["sharpe_daily"],
            "avg_net_profit_per_trade_pct": f["avg_net_profit_pct"],
        },
    }


def _json_default(o):
    if isinstance(o, float) and math.isinf(o):
        return "inf"
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, pd.Timestamp):
        return str(o)
    return str(o)


def registry_report(args: argparse.Namespace) -> int:
    """Every trial in the registry, with DSR recomputed against the registry's current N."""
    reg = Registry(args.registry)
    n, sigma = reg.n_trials(), reg.sigma_trials()
    out = {"n_trials": n, "sigma_trials_period": sigma, "trials": []}
    for row in reg.rows():
        returns = row.pop("daily_returns_json")
        if returns is not None:
            row["dsr"] = dsr.deflated_sharpe(np.array(json.loads(returns)), n, sigma).as_dict()
        out["trials"].append(row)
    print(json.dumps(out, indent=1, default=_json_default))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("strategy")
    r.add_argument("--seeds", type=int, default=200)
    r.add_argument("--registry", type=Path, default=STATE / "registry.sqlite")
    r.add_argument("--out", type=Path, default=OUT)
    r.add_argument("--no-register", action="store_true", help="dry harness check; writes no trial")
    r.add_argument(
        "--recompute",
        action="store_true",
        help="rebuild the report of an already-scored trial; registry read-only; refuses unless the recorded "
        "Sharpe, trade count and daily returns are reproduced exactly",
    )
    rr = sub.add_parser("registry", help="list trials; DSR against the current N")
    rr.add_argument("--registry", type=Path, default=STATE / "registry.sqlite")
    args = p.parse_args()
    return run(args) if args.cmd == "run" else registry_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
