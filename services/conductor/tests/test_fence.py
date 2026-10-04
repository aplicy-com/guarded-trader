"""R3: daily fence job (ledger-only), missed-run handling, manual transfers."""

import sqlite3
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import structlog

from conductor.application.capital import get_capital
from conductor.application.fence import record_manual_transfer, run_daily_fence
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.principal import ensure_principal
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, closed_view

D = Decimal
THRESH = D(25)


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)


def seed_profit(ledger: SqliteLedger, clock: Clock, *profits: str) -> None:
    ft = FakeFreqtrade()
    ft.closed_trades = [closed_view(i + 1, p) for i, p in enumerate(profits)]
    run_ingest(ledger, [FreqtradeInstance("primary", ft)], now=clock)


def fence(ledger: SqliteLedger, clock: Clock, cap: str | None = "10") -> object:
    return run_daily_fence(
        ledger,
        daily_profit_cap=None if cap is None else D(cap),
        manual_move_threshold=THRESH,
        now=clock,
    )


def test_fences_only_the_excess_over_the_cap_and_lowers_max_deployed(
    ledger: SqliteLedger, clock: Clock
) -> None:
    seed_profit(ledger, clock, "30")
    assert get_capital(ledger).max_deployed_capital == D(130)
    r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert (r.ran, r.fenced_amount, r.cap_configured) == (True, D(20), True)
    c = get_capital(ledger)
    assert (c.fenced_total, c.working_profit, c.max_deployed_capital) == (D(20), D(10), D(110))


def test_below_cap_fences_nothing_but_still_records_the_run(
    ledger: SqliteLedger, clock: Clock, db_path: Path
) -> None:
    seed_profit(ledger, clock, "4")
    r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert r.fenced_amount == 0
    assert sqlite3.connect(db_path).execute(
        "SELECT fenced_amount FROM fence_events"
    ).fetchall() == [("0",)]


def test_running_twice_on_the_same_utc_day_fences_once(
    ledger: SqliteLedger, clock: Clock, db_path: Path
) -> None:
    seed_profit(ledger, clock, "30")
    first = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    clock.at += timedelta(hours=3)
    second = run_daily_fence(
        ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock
    )
    assert (first.ran, second.ran, second.fenced_amount) == (True, False, D(0))
    assert get_capital(ledger).fenced_total == D(20)
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM fence_events").fetchone() == (1,)


def test_next_day_fences_only_new_excess(ledger: SqliteLedger, clock: Clock) -> None:
    seed_profit(ledger, clock, "30")
    run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    clock.at += timedelta(days=1)
    r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert r.fenced_amount == 0
    seed_profit(ledger, clock, "30", "5")
    clock.at += timedelta(days=1)
    r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert r.fenced_amount == D(5)
    assert get_capital(ledger).fenced_total == D(25)


def test_missed_days_are_reported_audited_and_caught_up(
    ledger: SqliteLedger, clock: Clock, db_path: Path
) -> None:
    seed_profit(ledger, clock, "5")
    run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    seed_profit(ledger, clock, "5", "40")  # profit arrives while "down"
    clock.at += timedelta(days=4)  # host was down for 3 UTC days
    with structlog.testing.capture_logs() as logs:
        r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert r.missed_days == (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7))
    assert r.fenced_amount == D(35)  # caught up on the very next run
    assert any(e["event"] == "fence_run_missed" and e["log_level"] == "warning" for e in logs)
    audit = (
        sqlite3.connect(db_path)
        .execute("SELECT action FROM audit_log WHERE action LIKE 'fence_run%' ORDER BY id")
        .fetchall()
    )
    assert ("fence_run_missed",) in audit


def test_no_cap_configured_fences_nothing_and_warns(ledger: SqliteLedger, clock: Clock) -> None:
    seed_profit(ledger, clock, "500")
    with structlog.testing.capture_logs() as logs:
        r = run_daily_fence(ledger, daily_profit_cap=None, manual_move_threshold=THRESH, now=clock)
    assert (r.fenced_amount, r.cap_configured) == (0, False)
    assert get_capital(ledger).max_deployed_capital == D(600)  # remains working profit (AC2.4)
    assert any(e["event"] == "fence_cap_not_configured" for e in logs)


def test_losses_are_never_fenced(ledger: SqliteLedger, clock: Clock) -> None:
    seed_profit(ledger, clock, "-30")
    r = run_daily_fence(ledger, daily_profit_cap=D(0), manual_move_threshold=THRESH, now=clock)
    assert r.fenced_amount == 0
    assert get_capital(ledger).max_deployed_capital == D(70)


def test_fence_makes_no_exchange_call(
    ledger: SqliteLedger, clock: Clock, freqtrade: FakeFreqtrade
) -> None:
    seed_profit(ledger, clock, "30")
    freqtrade.calls.clear()
    run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert freqtrade.calls == []


def test_move_due_logged_when_threshold_reached(ledger: SqliteLedger, clock: Clock) -> None:
    seed_profit(ledger, clock, "40")
    with structlog.testing.capture_logs() as logs:
        r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert r.move_due.over_threshold
    assert any(e["event"] == "manual_move_due" and e["unmoved"] == "30" for e in logs)


def test_move_due_after_thirty_days_even_below_threshold(
    ledger: SqliteLedger, clock: Clock
) -> None:
    seed_profit(ledger, clock, "15")
    run_daily_fence(
        ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock
    )  # fences 5
    clock.at += timedelta(days=29)
    assert not run_daily_fence(
        ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock
    ).move_due.due
    clock.at += timedelta(days=1)
    r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert (r.move_due.month_elapsed, r.move_due.over_threshold) == (True, False)


def test_transfer_resets_the_clock_and_reduces_unmoved(ledger: SqliteLedger, clock: Clock) -> None:
    seed_profit(ledger, clock, "40")
    run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)  # 30
    record_manual_transfer(
        ledger,
        amount=D(30),
        destination="cold wallet",
        exchange_tx_id="TX1",
        transferred_at=clock.at,
        operator="maduka",
        now=clock,
    )
    clock.at += timedelta(days=40)
    r = run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)
    assert (r.move_due.unmoved, r.move_due.due) == (D(0), False)


def test_clock_must_be_timezone_aware(ledger: SqliteLedger) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        run_daily_fence(
            ledger,
            daily_profit_cap=D(1),
            manual_move_threshold=THRESH,
            now=lambda: datetime(2026, 10, 4, 12),
        )


# ---- manual transfers ---------------------------------------------------------


def seed_fenced(ledger: SqliteLedger, clock: Clock, amount: str = "20") -> None:
    seed_profit(ledger, clock, str(D(amount) + 10))
    run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=THRESH, now=clock)


def transfer(
    ledger: SqliteLedger,
    clock: Clock,
    amount: str,
    tx: str = "TX1",
    overrides: dict[str, Any] | None = None,
    note: str | None = None,
) -> None:
    args: dict[str, Any] = {
        "amount": D(amount),
        "destination": "ledger-hw",
        "exchange_tx_id": tx,
        "transferred_at": clock.at - timedelta(hours=1),
        "operator": "maduka",
        "note": note,
        "now": clock,
        **(overrides or {}),
    }
    record_manual_transfer(ledger, **args)


def test_records_transfer_with_operator_and_audit(
    ledger: SqliteLedger, clock: Clock, db_path: Path
) -> None:
    seed_fenced(ledger, clock)
    transfer(ledger, clock, "12.5", note="first move")
    con = sqlite3.connect(db_path)
    assert con.execute(
        "SELECT amount, destination, exchange_tx_id, operator FROM manual_transfers"
    ).fetchall() == [("12.5", "ledger-hw", "TX1", "maduka")]
    assert con.execute(
        "SELECT actor, action FROM audit_log WHERE action='manual_transfer_recorded'"
    ).fetchall() == [("maduka", "manual_transfer_recorded")]


def test_transfer_cannot_exceed_fenced_but_unmoved(ledger: SqliteLedger, clock: Clock) -> None:
    seed_fenced(ledger, clock, "20")
    transfer(ledger, clock, "15", tx="A")
    with pytest.raises(ValueError, match="exceeds"):
        transfer(ledger, clock, "5.01", tx="B")
    transfer(ledger, clock, "5", tx="B")


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"amount": D(0)}, "amount"),
        ({"amount": D("-1")}, "amount"),
        ({"operator": "  "}, "operator"),
        ({"destination": ""}, "destination"),
        ({"exchange_tx_id": ""}, "exchange_tx_id"),
        ({"transferred_at": datetime(2026, 10, 4, 1)}, "timezone"),
        ({"transferred_at": datetime(2030, 1, 1, tzinfo=UTC)}, "future"),
    ],
)
def test_invalid_transfers_rejected_and_nothing_written(
    ledger: SqliteLedger, clock: Clock, db_path: Path, override: dict[str, Any], match: str
) -> None:
    seed_fenced(ledger, clock)
    with pytest.raises(ValueError, match=match):
        transfer(ledger, clock, "5", overrides=override)
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM manual_transfers").fetchone() == (
        0,
    )


def test_duplicate_exchange_tx_id_rejected(ledger: SqliteLedger, clock: Clock) -> None:
    seed_fenced(ledger, clock)
    transfer(ledger, clock, "5", tx="DUP")
    with pytest.raises(Exception, match=r"(?i)unique"):
        transfer(ledger, clock, "5", tx="DUP")


def test_concurrent_transfers_cannot_overdraw(
    ledger: SqliteLedger, clock: Clock, db_path: Path
) -> None:
    """Two writers race for the same 20 USD: the write lock serialises the check."""
    seed_fenced(ledger, clock, "20")
    ledgers = [
        SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))
        for _ in range(6)
    ]
    barrier = threading.Barrier(len(ledgers))
    outcomes: list[str] = []

    def worker(i: int, lg: SqliteLedger) -> None:
        barrier.wait()
        try:
            transfer(lg, clock, "15", tx=f"RACE{i}")
            outcomes.append("ok")
        except ValueError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=worker, args=(i, lg)) for i, lg in enumerate(ledgers)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(outcomes) == ["ok"] + ["rejected"] * (len(ledgers) - 1)
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM manual_transfers").fetchone() == (
        1,
    )
