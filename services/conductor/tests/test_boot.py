"""Fail-closed boot (ADR-0018): Freqtrade starts paused; Conductor starts it only if no halt."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from conductor.application.boot import BootGuard, start_if_clear
from conductor.application.halts import clear_halt, kill_switch
from conductor.application.ingest import FreqtradeInstance
from conductor.application.principal import ensure_principal
from conductor.application.risk import run_risk_cycle
from conductor.domain.halt import HaltType
from conductor.domain.risk import RiskLimits
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, closed_view

REPO = Path(__file__).parents[3]
LIMITS = RiskLimits(D(3), D(10), 3, 2)


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)


@pytest.fixture
def guard() -> BootGuard:
    return BootGuard()


def boot(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    guard: BootGuard,
    notifier: RecordingNotifier,
    *,
    equity_known: bool = True,
) -> tuple[object, ...]:
    return start_if_clear(ledger, instances, guard, equity_known=equity_known, notifier=notifier)


def test_a_freshly_booted_paused_freqtrade_is_started_when_no_halt_is_active(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == ["resume"]
    assert freqtrade.state == "running"
    assert any(t.startswith("BOOT primary") for t in notifier.sent)


def test_an_active_halt_withholds_the_start_and_it_is_not_retried(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    kill_switch(ledger, instances, operator="m", now=clock, notifier=notifier)
    freqtrade.control_calls.clear()
    freqtrade.state = "paused"
    for _ in range(3):
        boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == []
    assert freqtrade.state == "paused"


def test_a_freqtrade_restart_under_a_halt_never_runs_and_a_human_clear_still_resumes(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    r = kill_switch(ledger, instances, operator="m", now=clock, notifier=notifier)
    boot(ledger, instances, guard, notifier)
    freqtrade.startup_ts = (freqtrade.startup_ts or 0) + 60  # Freqtrade restarted, boots paused
    freqtrade.state = "paused"
    freqtrade.control_calls.clear()
    boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == [] and freqtrade.state == "paused"
    clear_halt(ledger, instances, halt_id=r.halt_id, operator="m", note=None, now=clock)
    assert freqtrade.state == "running"


def test_a_restart_is_detected_from_the_startup_marker_and_started_again(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    boot(ledger, instances, guard, notifier)
    assert freqtrade.state == "running"
    freqtrade.startup_ts = (freqtrade.startup_ts or 0) + 90
    freqtrade.state = "paused"  # the restarted bot boots paused
    boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == ["resume", "resume"]
    assert freqtrade.state == "running"


def test_a_pause_without_a_restart_is_left_alone(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    notifier: RecordingNotifier,
) -> None:
    boot(ledger, instances, guard, notifier)  # first sight: running, nothing to do
    freqtrade.state = "paused"  # same startup marker: someone paused it, not a boot
    boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == []
    assert freqtrade.state == "paused"


@pytest.mark.parametrize("state", ["running", "stopped", ""])
def test_only_a_paused_bot_is_ever_started(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    notifier: RecordingNotifier,
    state: str,
) -> None:
    freqtrade.state = state
    boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == []


def test_an_unreachable_freqtrade_is_retried_not_started_blindly(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    freqtrade.fail = True
    boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == []
    freqtrade.fail = False
    boot(ledger, instances, guard, notifier)
    assert freqtrade.control_calls == ["resume"]


def test_a_failed_start_stays_pending_and_is_retried(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    freqtrade.control_fail = True
    results = boot(ledger, instances, guard, notifier)
    assert [r.ok for r in results] == [False]  # type: ignore[attr-defined]
    assert freqtrade.state == "paused"
    freqtrade.control_fail = False
    boot(ledger, instances, guard, notifier)
    assert freqtrade.state == "running"


def test_unknown_equity_defers_the_start(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    boot(ledger, instances, guard, notifier, equity_known=False)
    assert freqtrade.state == "paused"
    boot(ledger, instances, guard, notifier)
    assert freqtrade.state == "running"


def test_a_halt_raised_between_the_check_and_the_start_wins(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    original = freqtrade.resume

    def resume_then_kill() -> None:  # a /kill lands while `start` is in flight
        original()
        from conductor.application.halts import engage_halt

        engage_halt(
            ledger,
            halt_type=HaltType.KILL_SWITCH,
            reason="race",
            actor="m",
            now=clock,
            notifier=notifier,
        )

    freqtrade.resume = resume_then_kill  # type: ignore[method-assign]
    boot(ledger, instances, guard, notifier)
    assert freqtrade.state == "paused"  # re-paused straight away, not 60 s later


def test_a_breach_found_in_the_same_risk_cycle_blocks_the_boot_start(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    freqtrade.closed_trades = [
        closed_view(i, "-1.50", close_date=clock.at.replace(hour=11, minute=i)) for i in (1, 2, 3)
    ]
    r = run_risk_cycle(ledger, instances, LIMITS, now=clock, notifier=notifier, boot_guard=guard)
    assert r.new_halt_ids  # consecutive losses / daily loss tripped in this very cycle
    assert "resume" not in freqtrade.control_calls
    assert freqtrade.state == "paused"


def test_a_clean_risk_cycle_starts_the_booted_bot(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    guard: BootGuard,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.state = "paused"
    r = run_risk_cycle(ledger, instances, LIMITS, now=clock, notifier=notifier, boot_guard=guard)
    assert [s.step for s in r.boot] == ["boot_start"]
    assert freqtrade.state == "running"


def test_the_shipped_freqtrade_config_boots_paused() -> None:
    cfg = json.loads((REPO / "services/freqtrade/user_data/config.dry_run.json").read_text())
    assert cfg["initial_state"] == "paused"
