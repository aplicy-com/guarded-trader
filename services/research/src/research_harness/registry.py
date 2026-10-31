"""Append-only trial registry (04-validation-upgrades.md section 1). SQLite, standard library.

Every candidate is written here *before* its backtest runs (pre-registration) and is never
updated or deleted: SQLite triggers abort any UPDATE or DELETE on either table. One
``strategy_hash`` scored on the canonical timerange is one trial; the trial count is the ``N``
the Deflated Sharpe Ratio deflates against. Random-entry null seeds are controls, not trials,
and are not registered.

Re-registering a ``strategy_hash`` that already has a result is refused, so re-running an
unchanged candidate cannot inflate or reset N; one registered but never scored (the run died)
is resumed under its original trial id. A changed parameter, fee, data snapshot or Freqtrade version is a
new hash and therefore a new trial.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    trial_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    strategy TEXT NOT NULL,
    family TEXT NOT NULL,
    strategy_hash TEXT NOT NULL UNIQUE,
    hypothesis TEXT NOT NULL CHECK (length(trim(hypothesis)) > 0),
    params_json TEXT NOT NULL,
    n_params INTEGER NOT NULL,
    canonical_timerange TEXT NOT NULL,
    fee REAL NOT NULL,
    data_snapshot_id TEXT NOT NULL,
    freqtrade_version TEXT NOT NULL,
    parent_trial_id TEXT REFERENCES trials(trial_id)
);
CREATE TABLE IF NOT EXISTS results (
    trial_id TEXT PRIMARY KEY REFERENCES trials(trial_id),
    created_at TEXT NOT NULL,
    sharpe_daily REAL NOT NULL,
    sharpe_period REAL NOT NULL,
    n_trades INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    daily_returns_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trials_no_update BEFORE UPDATE ON trials
    BEGIN SELECT RAISE(ABORT, 'trial registry is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trials_no_delete BEFORE DELETE ON trials
    BEGIN SELECT RAISE(ABORT, 'trial registry is append-only'); END;
CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results
    BEGIN SELECT RAISE(ABORT, 'trial registry is append-only'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results
    BEGIN SELECT RAISE(ABORT, 'trial registry is append-only'); END;
"""


class DuplicateTrialError(RuntimeError):
    """This exact strategy/params/fee/data/version combination is already registered."""


def strategy_hash(source: bytes, params: Mapping, fee: float, data_snapshot_id: str, freqtrade_version: str) -> str:
    h = hashlib.sha256()
    h.update(source)
    h.update(json.dumps(params, sort_keys=True).encode())
    h.update(f"{fee!r}|{data_snapshot_id}|{freqtrade_version}".encode())
    return h.hexdigest()


class Registry:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path)
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def preregister(
        self,
        *,
        strategy: str,
        family: str,
        hypothesis: str,
        params: Mapping,
        canonical_timerange: str,
        fee: float,
        data_snapshot_id: str,
        freqtrade_version: str,
        source: bytes,
        parent_trial_id: str | None = None,
    ) -> str:
        digest = strategy_hash(source, params, fee, data_snapshot_id, freqtrade_version)
        existing = self._db.execute(
            "SELECT t.trial_id, r.trial_id FROM trials t LEFT JOIN results r USING (trial_id)"
            " WHERE t.strategy_hash = ?",
            (digest,),
        ).fetchone()
        if existing and existing[1] is not None:
            raise DuplicateTrialError(f"{strategy} {digest[:12]} already registered and scored")
        if existing:
            # Registered, but the run died before scoring: finish that same trial, never a new one.
            return str(existing[0])
        trial_id = uuid.uuid4().hex[:12]
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO trials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        trial_id,
                        datetime.now(UTC).isoformat(),
                        strategy,
                        family,
                        digest,
                        hypothesis,
                        json.dumps(params, sort_keys=True),
                        len(params),
                        canonical_timerange,
                        fee,
                        data_snapshot_id,
                        freqtrade_version,
                        parent_trial_id,
                    ),
                )
        except sqlite3.IntegrityError as e:
            if "strategy_hash" in str(e):
                raise DuplicateTrialError(f"{strategy} {digest[:12]} already registered") from e
            raise
        return trial_id

    def record_result(
        self,
        trial_id: str,
        *,
        sharpe_daily: float,
        sharpe_period: float,
        n_trades: int,
        metrics: Mapping,
        daily_returns: list[float],
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO results VALUES (?,?,?,?,?,?,?)",
                (
                    trial_id,
                    datetime.now(UTC).isoformat(),
                    sharpe_daily,
                    sharpe_period,
                    n_trades,
                    json.dumps(metrics, sort_keys=True, default=str),
                    json.dumps(daily_returns),
                ),
            )

    def n_trials(self) -> int:
        """Every registered trial counts, scored or not: hiding failures understates N."""
        return int(self._db.execute("SELECT COUNT(*) FROM trials").fetchone()[0])

    def sigma_trials(self) -> float | None:
        """Cross-trial std of per-period Sharpe over scored trials; None below two."""
        vals = [r[0] for r in self._db.execute("SELECT sharpe_period FROM results")]
        vals = [v for v in vals if not math.isnan(v)]
        return statistics.stdev(vals) if len(vals) >= 2 else None

    def rows(self) -> list[dict]:
        cur = self._db.execute(
            "SELECT t.trial_id, t.created_at, t.strategy, t.family, t.strategy_hash, t.hypothesis,"
            " t.params_json, t.canonical_timerange, t.fee, t.data_snapshot_id,"
            " t.freqtrade_version, r.sharpe_daily, r.n_trades, r.daily_returns_json"
            " FROM trials t LEFT JOIN results r USING (trial_id) ORDER BY t.created_at"
        )
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur]
