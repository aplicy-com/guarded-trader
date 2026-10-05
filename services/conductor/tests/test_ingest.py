"""Ingest: idempotent upsert, restart safety, instance isolation, snapshots."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import structlog

from conductor.adapters.freqtrade import FreqtradeRestClient
from conductor.application import ingest as ingest_mod
from conductor.application.capital import get_capital
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.principal import ensure_principal
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, closed_view, open_view

D = Decimal


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)


def count(db: Path, table: str, where: str = "1") -> int:
    sql = f"SELECT count(*) FROM {table} WHERE {where}"  # noqa: S608
    return int(sqlite3.connect(db).execute(sql).fetchone()[0])


def test_first_ingest_inserts_open_and_closed(
    ledger: SqliteLedger, instances: list[FreqtradeInstance], freqtrade: FakeFreqtrade, clock: Clock
) -> None:
    freqtrade.open_trades = [open_view(10)]
    freqtrade.closed_trades = [closed_view(1, "2.50"), closed_view(2, "-1.00")]
    r = run_ingest(ledger, instances, now=clock)
    assert (r.inserted, r.updated, r.unchanged, r.failed_instances) == (3, 0, 0, ())
    assert get_capital(ledger).realized_profit == D("1.50")


def test_duplicate_ingest_is_idempotent(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    db_path: Path,
) -> None:
    freqtrade.open_trades = [open_view(10)]
    freqtrade.closed_trades = [closed_view(1, "2.50")]
    run_ingest(ledger, instances, now=clock)
    before = sqlite3.connect(db_path).execute("SELECT * FROM trades ORDER BY id").fetchall()
    clock.at = datetime(2026, 10, 4, 12, 5, tzinfo=UTC)
    r2 = run_ingest(ledger, instances, now=clock)
    r3 = run_ingest(ledger, instances, now=clock)
    assert (r2.inserted, r2.updated, r2.unchanged) == (0, 0, 2)
    assert r3.unchanged == 2
    assert sqlite3.connect(db_path).execute("SELECT * FROM trades ORDER BY id").fetchall() == before
    assert count(db_path, "trades") == 2
    assert count(db_path, "equity_snapshots") == 1  # unchanged state is not re-snapshotted


def test_restart_idempotency_new_process_same_database(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    db_path: Path,
) -> None:
    freqtrade.closed_trades = [closed_view(1, "2.50"), closed_view(2, "1.25")]
    run_ingest(ledger, instances, now=clock)
    restarted = SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))
    r = run_ingest(restarted, instances, now=clock)
    assert (r.inserted, r.updated, r.unchanged) == (0, 0, 2)
    assert get_capital(restarted).realized_profit == D("3.75")
    assert count(db_path, "trades") == 2


def test_open_trade_becomes_closed_in_place(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    db_path: Path,
) -> None:
    freqtrade.open_trades = [open_view(7)]
    run_ingest(ledger, instances, now=clock)
    assert get_capital(ledger).realized_profit == 0
    freqtrade.open_trades = []
    freqtrade.closed_trades = [closed_view(7, "3.00")]
    r = run_ingest(ledger, instances, now=clock)
    assert (r.inserted, r.updated) == (0, 1)
    assert count(db_path, "trades") == 1
    assert get_capital(ledger).realized_profit == D("3.00")


def test_closed_trade_is_never_reopened_by_a_stale_open_snapshot(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    db_path: Path,
) -> None:
    freqtrade.closed_trades = [closed_view(7, "3.00")]
    run_ingest(ledger, instances, now=clock)
    freqtrade.open_trades = [open_view(7)]  # stale/odd snapshot of the same id
    freqtrade.closed_trades = []
    r = run_ingest(ledger, instances, now=clock)
    assert r.unchanged == 1
    assert get_capital(ledger).realized_profit == D("3.00")
    assert count(db_path, "trades", "is_open = 1") == 0


def test_same_trade_id_on_two_instances_are_distinct_rows(
    ledger: SqliteLedger, clock: Clock, db_path: Path
) -> None:
    a, b = FakeFreqtrade(), FakeFreqtrade()
    a.closed_trades = [closed_view(1, "1.00")]
    b.closed_trades = [closed_view(1, "5.00")]
    both = [FreqtradeInstance("paper-a", a), FreqtradeInstance("paper-b", b)]
    run_ingest(ledger, both, now=clock)
    run_ingest(ledger, both, now=clock)
    assert count(db_path, "trades") == 2
    assert get_capital(ledger).realized_profit == D("6.00")


def test_unreachable_instance_does_not_block_others_and_unrealized_is_unknown(
    ledger: SqliteLedger, clock: Clock, db_path: Path
) -> None:
    good, bad = FakeFreqtrade(), FakeFreqtrade(fail=True)
    good.closed_trades = [closed_view(1, "1.00")]
    r = run_ingest(
        ledger, [FreqtradeInstance("good", good), FreqtradeInstance("bad", bad)], now=clock
    )
    assert r.failed_instances == ("bad",)
    assert r.inserted == 1
    row = (
        sqlite3.connect(db_path)
        .execute("SELECT unrealized_profit, equity FROM equity_snapshots")
        .fetchone()
    )
    assert row == (None, None)


def test_unrealized_pnl_and_equity_snapshot(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    db_path: Path,
) -> None:
    freqtrade.open_trades = [open_view(1, profit_abs=D("1.5")), open_view(2, profit_abs=D("-0.5"))]
    freqtrade.closed_trades = [closed_view(3, "2.00")]
    run_ingest(ledger, instances, now=clock)
    row = (
        sqlite3.connect(db_path)
        .execute(
            "SELECT principal, realized_profit, unrealized_profit, equity, max_deployed_capital"
            " FROM equity_snapshots"
        )
        .fetchone()
    )
    assert row == ("100", "2.00", "1.0", "103.00", "102.00")


def test_pagination_collects_every_closed_trade(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest_mod, "PAGE_SIZE", 2)
    freqtrade.closed_trades = [closed_view(i, "1.00") for i in range(1, 6)]
    r = run_ingest(ledger, instances, now=clock)
    assert r.inserted == 5
    assert get_capital(ledger).realized_profit == D(5)


def test_closed_trade_without_profit_fails_the_instance_not_silently_zero(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
) -> None:
    freqtrade.closed_trades = [replace(closed_view(1), close_profit_abs=None)]
    with structlog.testing.capture_logs():
        r = run_ingest(ledger, instances, now=clock)
    assert r.failed_instances == ("primary",)
    assert r.inserted == 0


def test_decimal_profit_sums_are_exact(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
) -> None:
    freqtrade.closed_trades = [closed_view(1, "0.1"), closed_view(2, "0.2")]
    run_ingest(ledger, instances, now=clock)
    assert get_capital(ledger).realized_profit == D("0.3")


def test_ingest_through_the_real_read_only_client_with_recorded_fixtures(
    ledger: SqliteLedger, clock: Clock, fixture_json: object, db_path: Path
) -> None:
    from collections.abc import Callable
    from typing import Any, cast

    load = cast(Callable[[str], Any], fixture_json)
    routes = {"/api/v1/status": "status", "/api/v1/trades": "trades"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=load(routes[request.url.path]))

    client = FreqtradeRestClient("http://ft:8080", "u", "p", transport=httpx.MockTransport(handler))
    inst = [FreqtradeInstance("primary", client)]
    first = run_ingest(ledger, inst, now=clock)
    second = run_ingest(ledger, inst, now=clock)
    assert first.failed_instances == ()
    assert first.inserted == load("trades")["total_trades"] + len(load("status"))
    assert (second.inserted, second.updated) == (0, 0)
    # recorded dry-run ETH trade: exact decimal profit survived the float JSON
    assert sqlite3.connect(db_path).execute(
        "SELECT close_profit_abs FROM trades WHERE ft_trade_id = ?",
        (load("trades")["trades"][0]["trade_id"],),
    ).fetchone() == (str(load("trades")["trades"][0]["close_profit_abs"]),)
