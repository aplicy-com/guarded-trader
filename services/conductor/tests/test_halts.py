"""Halt paths: kill switch, nuclear, enforcement, clearing, persistence across restarts."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from conductor.application.halts import clear_halt, enforce_halts, engage_halt, kill_switch, nuclear
from conductor.application.ingest import FreqtradeInstance
from conductor.application.principal import ensure_principal
from conductor.domain.halt import HaltType
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, open_view

NO_SLEEP = lambda _s: None  # noqa: E731


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    from decimal import Decimal

    ensure_principal(ledger, Decimal(100), notifier=notifier, now=clock)


def active(ledger: SqliteLedger) -> list[tuple[int, HaltType, str | None]]:
    with ledger.transaction(write=False) as repo:
        return [(h.id, h.halt_type, h.instance) for h in repo.active_halts()]


# ---- kill switch ----------------------------------------------------------------


def test_kill_switch_persists_pauses_alerts_and_audits(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
    db_path: Path,
) -> None:
    r = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    assert r.ok
    assert r.created
    assert freqtrade.state == "paused"
    assert freqtrade.control_calls == ["pause_entries"]
    assert active(ledger) == [(r.halt_id, HaltType.KILL_SWITCH, None)]
    assert len(notifier.sent) == 1
    assert "kill_switch" in notifier.sent[0]
    actions = [
        a for (a,) in sqlite3.connect(db_path).execute("SELECT action FROM audit_log ORDER BY id")
    ]
    assert "halt_engaged" in actions
    assert "kill_switch_applied" in actions


def test_kill_switch_is_idempotent(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    first = kill_switch(ledger, instances, operator="a", now=clock, notifier=notifier)
    second = kill_switch(ledger, instances, operator="b", now=clock, notifier=notifier)
    assert (first.created, second.created, second.halt_id) == (True, False, first.halt_id)
    assert len(notifier.sent) == 1


def test_kill_switch_with_freqtrade_down_still_records_the_halt_and_reports_failure(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.fail = True
    r = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    assert not r.ok
    assert active(ledger)  # recorded first: nothing can trade "unhalted" in the ledger's eyes
    freqtrade.fail = False  # Freqtrade comes back (running) ...
    results = enforce_halts(ledger, instances)  # ... and the next cycle pauses it
    assert [x.ok for x in results] == [True]
    assert freqtrade.state == "paused"


def test_operator_name_is_required(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    with pytest.raises(ValueError, match="operator"):
        kill_switch(ledger, instances, operator="  ", now=clock, notifier=notifier)
    assert active(ledger) == []


# ---- enforcement / restart persistence -----------------------------------------


def test_halt_survives_a_conductor_restart_and_is_reapplied_after_freqtrade_restart(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
    db_path: Path,
) -> None:
    kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    # Conductor process restarts: brand-new engine over the same file.
    reborn = SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))
    assert len(active(reborn)) == 1
    # Freqtrade restarts too and comes back "running" (its configured initial_state).
    freqtrade.state = "running"
    freqtrade.control_calls.clear()
    enforce_halts(reborn, instances)
    assert freqtrade.state == "paused"
    assert freqtrade.control_calls == ["pause_entries"]


def test_enforcement_is_quiet_when_nothing_is_wrong(
    ledger: SqliteLedger, instances: list[FreqtradeInstance], freqtrade: FakeFreqtrade
) -> None:
    assert enforce_halts(ledger, instances) == ()  # no halts: not even a read of Freqtrade
    assert freqtrade.calls == []


@pytest.mark.parametrize("state", ["paused", "stopped"])
def test_already_blocked_instance_is_left_alone(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
    state: str,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.state = state
    assert enforce_halts(ledger, instances) == ()
    assert freqtrade.control_calls == []


def test_unknown_state_is_treated_as_running(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.state = ""
    enforce_halts(ledger, instances)
    assert freqtrade.control_calls == ["pause_entries"]


def test_unreachable_freqtrade_during_enforcement_fails_closed_without_raising_then_retries(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.fail = True
    results = enforce_halts(ledger, instances)
    assert [(r.step, r.ok) for r in results] == [("check_state", False)]
    assert len(active(ledger)) == 1  # still halted
    freqtrade.fail = False
    freqtrade.state = "running"
    assert [r.ok for r in enforce_halts(ledger, instances)] == [True]
    assert freqtrade.state == "paused"


def test_pause_failure_is_reported_and_retried(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.control_fail = True
    assert [r.ok for r in enforce_halts(ledger, instances)] == [False]
    freqtrade.control_fail = False
    assert [r.ok for r in enforce_halts(ledger, instances)] == [True]


def test_enforcement_never_resumes_anything(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.state = "paused"
    for _ in range(5):
        clock.at += timedelta(days=1)
        enforce_halts(ledger, instances)
    assert "resume" not in freqtrade.control_calls
    assert len(active(ledger)) == 1  # time alone never clears a halt


def test_instance_scoped_halt_only_pauses_that_instance(
    ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier
) -> None:
    a, b = FakeFreqtrade(), FakeFreqtrade()
    both = [FreqtradeInstance("a", a, a), FreqtradeInstance("b", b, b)]
    engage_halt(
        ledger,
        halt_type=HaltType.CONSECUTIVE_LOSSES,
        reason="r",
        actor="system",
        now=clock,
        notifier=notifier,
        instance="a",
    )
    enforce_halts(ledger, both)
    assert (a.state, b.state) == ("paused", "running")


def test_instance_without_write_access_is_reported_not_ignored(
    ledger: SqliteLedger, freqtrade: FakeFreqtrade, clock: Clock, notifier: RecordingNotifier
) -> None:
    ro = [FreqtradeInstance("primary", freqtrade)]
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    (res,) = enforce_halts(ledger, ro)
    assert (res.ok, res.detail) == (False, "no write access configured")


# ---- nuclear --------------------------------------------------------------------


def test_nuclear_sequence_cancels_exits_then_stops(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
    db_path: Path,
) -> None:
    freqtrade.open_trades = [
        open_view(1, has_open_orders=True),
        open_view(2),
        open_view(3, has_open_orders=True),
    ]
    r = nuclear(ledger, instances, operator="maduka", now=clock, notifier=notifier, sleep=NO_SLEEP)
    assert r.ok
    assert freqtrade.control_calls == [
        "pause_entries",
        "cancel:1",
        "cancel:3",
        "force_exit_all",
        "stop",
    ]
    assert freqtrade.state == "stopped"
    assert active(ledger) == [(r.halt_id, HaltType.NUCLEAR, None)]
    row = (
        sqlite3.connect(db_path)
        .execute("SELECT detail FROM audit_log WHERE action='nuclear_applied'")
        .fetchone()
    )
    assert "confirm_flat:ok" in row[0]


def test_nuclear_with_nothing_open_just_pauses_and_stops(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    r = nuclear(ledger, instances, operator="maduka", now=clock, notifier=notifier, sleep=NO_SLEEP)
    assert r.ok
    assert freqtrade.control_calls == ["pause_entries", "stop"]


def test_nuclear_not_flat_in_time_leaves_the_bot_paused_not_stopped(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1)]
    freqtrade.exit_works = False
    r = nuclear(
        ledger,
        instances,
        operator="maduka",
        now=clock,
        notifier=notifier,
        sleep=NO_SLEEP,
        flatten_wait_seconds=6,
    )
    assert not r.ok
    assert "stop" not in freqtrade.control_calls  # an unmanaged position must not be orphaned
    assert freqtrade.state == "paused"
    assert any(s.step == "confirm_flat" and not s.ok for s in r.steps)
    assert len(active(ledger)) == 1


def test_nuclear_failure_on_one_instance_does_not_skip_the_other(
    ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier
) -> None:
    bad, good = FakeFreqtrade(fail=True), FakeFreqtrade()
    both = [FreqtradeInstance("bad", bad, bad), FreqtradeInstance("good", good, good)]
    r = nuclear(ledger, both, operator="maduka", now=clock, notifier=notifier, sleep=NO_SLEEP)
    assert not r.ok
    assert good.state == "stopped"


def test_nuclear_halt_is_reapplied_after_restart_but_never_re_flattens(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    nuclear(ledger, instances, operator="maduka", now=clock, notifier=notifier, sleep=NO_SLEEP)
    freqtrade.state = "running"  # restarted
    freqtrade.open_trades = [open_view(9)]
    freqtrade.control_calls.clear()
    enforce_halts(ledger, instances)
    assert freqtrade.control_calls == ["pause_entries"]


# ---- clearing ---------------------------------------------------------------------


def test_clear_requires_a_named_operator_and_a_real_halt(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    r = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    with pytest.raises(ValueError, match="operator"):
        clear_halt(ledger, instances, halt_id=r.halt_id, operator="", note=None, now=clock)
    with pytest.raises(ValueError, match="no halt"):
        clear_halt(ledger, instances, halt_id=999, operator="maduka", note=None, now=clock)
    assert len(active(ledger)) == 1


def test_clear_records_operator_resumes_and_audits(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
    db_path: Path,
) -> None:
    r = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    clock.at += timedelta(hours=2)
    c = clear_halt(
        ledger, instances, halt_id=r.halt_id, operator="maduka", note="reviewed", now=clock
    )
    assert (c.newly_cleared, c.ok, c.still_active) == (True, True, ())
    assert freqtrade.state == "running"
    assert active(ledger) == []
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT operator, note, cleared_at FROM halt_clears").fetchall() == [
        ("maduka", "reviewed", "2026-10-04T14:00:00.000000+00:00")
    ]
    assert con.execute("SELECT actor FROM audit_log WHERE action='halt_cleared'").fetchall() == [
        ("maduka",)
    ]


def test_clear_does_not_resume_while_another_halt_still_covers_the_instance(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    kill = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    engage_halt(
        ledger,
        halt_type=HaltType.MAX_DRAWDOWN,
        reason="dd",
        actor="system",
        now=clock,
        notifier=notifier,
    )
    c = clear_halt(ledger, instances, halt_id=kill.halt_id, operator="maduka", note=None, now=clock)
    assert [h.halt_type for h in c.still_active] == [HaltType.MAX_DRAWDOWN]
    assert "resume" not in freqtrade.control_calls
    assert freqtrade.state == "paused"


def test_failed_resume_leaves_freqtrade_paused_and_a_rerun_retries(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    r = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    freqtrade.control_fail = True
    c = clear_halt(ledger, instances, halt_id=r.halt_id, operator="maduka", note=None, now=clock)
    assert (c.newly_cleared, c.ok) == (True, False)
    assert freqtrade.state == "paused"  # fail closed
    freqtrade.control_fail = False
    again = clear_halt(
        ledger, instances, halt_id=r.halt_id, operator="maduka", note=None, now=clock
    )
    assert (again.newly_cleared, again.ok) == (False, True)
    assert freqtrade.state == "running"


def test_a_halt_can_only_be_cleared_once_at_the_database_level(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    r = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    clear_halt(ledger, instances, halt_id=r.halt_id, operator="maduka", note=None, now=clock)
    with pytest.raises(sa.exc.IntegrityError), ledger.transaction() as repo:
        repo.clear_halt(r.halt_id, clock.at, "someone", None)


def test_new_halt_after_clear_is_a_new_row(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    a = kill_switch(ledger, instances, operator="m", now=clock, notifier=notifier)
    clear_halt(ledger, instances, halt_id=a.halt_id, operator="m", note=None, now=clock)
    b = kill_switch(ledger, instances, operator="m", now=clock, notifier=notifier)
    assert b.created
    assert b.halt_id != a.halt_id
