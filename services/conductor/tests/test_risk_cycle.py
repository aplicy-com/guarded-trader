"""Risk cycle: each breaker from the ledger, persisted halts, resets after a human clear."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import structlog

from conductor.application.halts import clear_halt, kill_switch
from conductor.application.ingest import FreqtradeInstance
from conductor.application.principal import ensure_principal
from conductor.application.risk import run_risk_cycle
from conductor.domain.halt import HaltType
from conductor.domain.risk import RiskLimits
from conductor.infrastructure.config import Settings
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.main import create_app
from fakes import Clock, FakeFreqtrade, FakeFx, RecordingNotifier, closed_view, open_view

D = Decimal
LIMITS = RiskLimits(D(3), D(10), 3, 2)
TODAY_MORNING = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)  # clock is 2026-10-04 12:00Z


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)


def cycle(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> object:
    return run_risk_cycle(ledger, instances, LIMITS, now=clock, notifier=notifier)


def halts(ledger: SqliteLedger) -> list[tuple[HaltType, str | None]]:
    with ledger.transaction(write=False) as repo:
        return [(h.halt_type, h.instance) for h in repo.active_halts()]


def test_healthy_account_creates_no_halt_and_touches_nothing(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1), open_view(2)]
    r = cycle(ledger, instances, clock, notifier)
    assert r.breaches == ()  # type: ignore[attr-defined]
    assert halts(ledger) == []
    assert freqtrade.control_calls == []
    assert notifier.sent == []


def test_r7_third_open_position_halts_and_pauses_entries(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [
        open_view(1, stake_amount=D(10)),
        open_view(2, stake_amount=D(10)),
        open_view(3, stake_amount=D(10)),
    ]
    r = cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.MAX_POSITIONS, None)]
    assert freqtrade.state == "paused"
    assert len(r.new_halt_ids) == 1  # type: ignore[attr-defined]
    assert "max_positions" in notifier.sent[0]


def test_r2_exposure_above_max_deployed_capital_halts(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [
        open_view(1, stake_amount=D(60)),
        open_view(2, stake_amount=D("40.01")),
    ]
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.CAPITAL_EXCEEDED, None)]
    assert freqtrade.state == "paused"


def test_r2_exposure_exactly_at_the_ceiling_is_allowed(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1, stake_amount=D(50)), open_view(2, stake_amount=D(50))]
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == []


def test_daily_loss_today_halts(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.closed_trades = [closed_view(1, "-3.00", close_date=TODAY_MORNING)]
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.DAILY_LOSS, None)]
    assert freqtrade.state == "paused"


def test_daily_loss_counts_unrealized(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1, profit_abs=D("-3.5"))]
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.DAILY_LOSS, None)]


def test_an_old_loss_is_not_mistaken_for_todays_on_first_run(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    # -5 USD realized on 2026-09-14, no snapshot history yet (first day after deploy).
    freqtrade.closed_trades = [closed_view(1, "-5.00")]
    cycle(ledger, instances, clock, notifier)
    assert HaltType.DAILY_LOSS not in [t for t, _ in halts(ledger)]


def test_drawdown_from_peak_halts(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1, profit_abs=D(10))]
    cycle(ledger, instances, clock, notifier)  # equity 110: the peak
    assert halts(ledger) == []
    clock.at += timedelta(minutes=5)
    freqtrade.open_trades = [open_view(1, profit_abs=D(-2))]  # equity 98: 10.9% below 110
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.MAX_DRAWDOWN, None)]


def test_consecutive_losses_halt_only_that_instance(
    ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier
) -> None:
    a, b = FakeFreqtrade(), FakeFreqtrade()
    a.closed_trades = [closed_view(i, "-0.10") for i in (1, 2, 3)]
    b.closed_trades = [closed_view(1, "-0.10"), closed_view(2, "0.50"), closed_view(3, "-0.10")]
    both = [FreqtradeInstance("a", a, a), FreqtradeInstance("b", b, b)]
    cycle(ledger, both, clock, notifier)
    assert halts(ledger) == [(HaltType.CONSECUTIVE_LOSSES, "a")]
    assert (a.state, b.state) == ("paused", "running")


def test_a_breach_halts_once_and_alerts_once(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(i, stake_amount=D(10)) for i in (1, 2, 3)]
    for _ in range(4):
        clock.at += timedelta(minutes=1)
        cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.MAX_POSITIONS, None)]
    assert len(notifier.sent) == 1


def test_halt_never_lifts_by_itself_when_the_condition_goes_away(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(i, stake_amount=D(10), profit_abs=D(0)) for i in (1, 2, 3)]
    cycle(ledger, instances, clock, notifier)
    freqtrade.open_trades = []  # positions closed flat
    for _ in range(3):
        clock.at += timedelta(days=1)
        cycle(ledger, instances, clock, notifier)
    assert len(halts(ledger)) == 1
    assert freqtrade.state == "paused"
    assert "resume" not in freqtrade.control_calls


def test_daily_loss_breaker_resets_from_the_clear_not_the_same_loss_again(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.closed_trades = [closed_view(1, "-3.50", close_date=TODAY_MORNING)]
    cycle(ledger, instances, clock, notifier)
    (halt_id,) = [h.id for h in _active(ledger)]
    clock.at += timedelta(hours=1)
    clear_halt(ledger, instances, halt_id=halt_id, operator="maduka", note="reviewed", now=clock)
    assert freqtrade.state == "running"
    clock.at += timedelta(minutes=1)
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == []  # same loss, but measured from the human's re-enable
    clock.at += timedelta(minutes=5)
    freqtrade.closed_trades.append(closed_view(2, "-3.50", close_date=clock.at))  # a NEW 3.5% loss
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.DAILY_LOSS, None)]


def test_drawdown_peak_resets_at_the_clear(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1, profit_abs=D(10))]
    cycle(ledger, instances, clock, notifier)
    clock.at += timedelta(minutes=5)
    freqtrade.open_trades = [open_view(1, profit_abs=D(-2))]
    cycle(ledger, instances, clock, notifier)
    (halt,) = _active(ledger)
    assert halt.halt_type is HaltType.MAX_DRAWDOWN
    clock.at += timedelta(minutes=5)
    clear_halt(ledger, instances, halt_id=halt.id, operator="maduka", note=None, now=clock)
    clock.at += timedelta(minutes=5)
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == []  # peak is now the equity at the clear, not the old 110


def test_loss_streak_counts_only_trades_after_the_clear(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.closed_trades = [
        closed_view(i, "-0.10", close_date=TODAY_MORNING - timedelta(hours=i)) for i in (1, 2, 3)
    ]
    cycle(ledger, instances, clock, notifier)
    (halt,) = _active(ledger)
    clock.at += timedelta(hours=1)
    clear_halt(ledger, instances, halt_id=halt.id, operator="maduka", note=None, now=clock)
    clock.at += timedelta(minutes=5)
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == []
    for n in (4, 5, 6):  # three fresh losses after the clear
        clock.at += timedelta(minutes=5)
        freqtrade.closed_trades.append(closed_view(n, "-0.10", close_date=clock.at))
    cycle(ledger, instances, clock, notifier)
    assert halts(ledger) == [(HaltType.CONSECUTIVE_LOSSES, "primary")]


def test_persistent_r7_breach_rehalts_after_a_premature_clear(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(i, stake_amount=D(10)) for i in (1, 2, 3)]
    cycle(ledger, instances, clock, notifier)
    (halt,) = _active(ledger)
    clear_halt(ledger, instances, halt_id=halt.id, operator="maduka", note=None, now=clock)
    assert freqtrade.state == "running"
    clock.at += timedelta(minutes=1)
    cycle(ledger, instances, clock, notifier)
    assert [(h.halt_type, h.id != halt.id) for h in _active(ledger)] == [
        (HaltType.MAX_POSITIONS, True)
    ]
    assert freqtrade.state == "paused"


def test_unreachable_instance_skips_equity_rules_but_still_enforces_position_cap(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(i, stake_amount=D(10)) for i in (1, 2, 3)]
    cycle(ledger, instances, clock, notifier)  # ledger now knows 3 open positions
    # break the halt so we can watch an outage cycle on its own
    (halt,) = _active(ledger)
    clear_halt(ledger, instances, halt_id=halt.id, operator="m", note=None, now=clock)
    freqtrade.fail = True
    with structlog.testing.capture_logs() as logs:
        r = cycle(ledger, instances, clock, notifier)
    assert r.equity_known is False  # type: ignore[attr-defined]
    assert any(e["event"] == "risk_equity_unknown" for e in logs)
    assert halts(ledger) == [(HaltType.MAX_POSITIONS, None)]  # ledger-derived, still evaluated
    assert r.enforcement and not r.enforcement[0].ok  # type: ignore[attr-defined]
    freqtrade.fail = False
    freqtrade.state = "running"
    freqtrade.open_trades = []
    r2 = cycle(ledger, instances, clock, notifier)
    assert [s.ok for s in r2.enforcement] == [True]  # type: ignore[attr-defined]
    assert freqtrade.state == "paused"


def test_kill_switch_and_automatic_halt_coexist(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    kill = kill_switch(ledger, instances, operator="maduka", now=clock, notifier=notifier)
    freqtrade.open_trades = [open_view(i, stake_amount=D(10)) for i in (1, 2, 3)]
    cycle(ledger, instances, clock, notifier)
    clear_halt(ledger, instances, halt_id=kill.halt_id, operator="maduka", note=None, now=clock)
    assert freqtrade.state == "paused"  # the R7 halt still holds


def _active(ledger: SqliteLedger) -> list:  # type: ignore[type-arg]
    with ledger.transaction(write=False) as repo:
        return repo.active_halts()


# ---- startup re-application through the real composition root ----------------------


def test_create_app_reapplies_a_persisted_halt_on_startup(
    settings: Settings, db_path: Path, clock: Clock, notifier: RecordingNotifier
) -> None:
    ft = FakeFreqtrade()
    inst = [FreqtradeInstance("primary", ft, ft)]
    create_app(settings, instances=inst, fx=FakeFx(), clock=clock)
    ledger = SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))
    kill_switch(ledger, inst, operator="maduka", now=clock, notifier=notifier)
    # Everything restarts: Freqtrade comes back running; Conductor boots a fresh app.
    ft.state = "running"
    ft.control_calls.clear()
    create_app(settings, instances=inst, fx=FakeFx(), clock=clock)
    assert ft.state == "paused"
    assert ft.control_calls == ["pause_entries"]


def test_create_app_does_not_fail_to_start_when_freqtrade_is_down_during_a_halt(
    settings: Settings, db_path: Path, clock: Clock, notifier: RecordingNotifier
) -> None:
    ft = FakeFreqtrade()
    inst = [FreqtradeInstance("primary", ft, ft)]
    create_app(settings, instances=inst, fx=FakeFx(), clock=clock)
    ledger = SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))
    kill_switch(ledger, inst, operator="maduka", now=clock, notifier=notifier)
    ft.fail = True
    create_app(settings, instances=inst, fx=FakeFx(), clock=clock)  # must not raise
    assert len(_active(ledger)) == 1
