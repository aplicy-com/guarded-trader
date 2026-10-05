"""R5 startup check (application level): live-only, fails closed, per pair."""

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.isolation import (
    IsolationCheckUnavailableError,
    run_startup_isolation_check,
)
from conductor.application.startup import run_startup_checks
from conductor.domain.isolation import AccountIsolationError
from conductor.domain.trading_mode import TradingMode
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.main import create_app
from conftest import make_settings
from fakes import Clock, FakeFreqtrade, RecordingNotifier, open_view

D = Decimal


def check(
    mode: TradingMode,
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    notifier: RecordingNotifier,
    clock: Clock,
) -> object:
    return run_startup_isolation_check(mode, ledger, instances, notifier=notifier, now=clock)


def test_dry_run_is_a_logged_noop_and_never_calls_freqtrade(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    freqtrade.balance_by_currency = {"BTC": D("5")}  # would be a violation in live
    assert check(TradingMode.DRY_RUN, ledger, instances, notifier, clock) == ()
    assert freqtrade.calls == []
    assert notifier.sent == []


def test_live_clean_account_passes(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    freqtrade.balance_by_currency = {"USD": D(100)}
    assert check(TradingMode.LIVE, ledger, instances, notifier, clock) == ()


def test_live_preexisting_balance_aborts_alerts_and_audits(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
    db_path: Path,
) -> None:
    freqtrade.balance_by_currency = {"USD": D(100), "BTC": D("0.02")}
    with pytest.raises(AccountIsolationError) as exc:
        check(TradingMode.LIVE, ledger, instances, notifier, clock)
    assert [(v.pair, v.unexplained) for v in exc.value.violations] == [("BTC/USD", D("0.02"))]
    assert len(notifier.sent) == 1
    assert "BTC/USD" in notifier.sent[0]
    assert sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM audit_log WHERE action='isolation_violation'"
    ).fetchone() == (1,)


def test_system_bought_open_position_is_explained_but_extra_is_not(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    freqtrade.open_trades = [open_view(1, "ETH/USD", amount="0.5")]
    run_ingest(ledger, instances, now=clock)
    freqtrade.balance_by_currency = {"ETH": D("0.5")}
    assert check(TradingMode.LIVE, ledger, instances, notifier, clock) == ()
    freqtrade.balance_by_currency = {"ETH": D("0.51")}
    with pytest.raises(AccountIsolationError) as exc:
        check(TradingMode.LIVE, ledger, instances, notifier, clock)
    assert exc.value.violations[0].unexplained == D("0.01")


def test_shortfall_in_one_pair_does_not_mask_excess_in_another(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    freqtrade.open_trades = [open_view(1, "ETH/USD", amount="0.5")]
    run_ingest(ledger, instances, now=clock)
    freqtrade.balance_by_currency = {"ETH": D(0), "SOL": D("3")}  # ETH short, SOL unexplained
    with pytest.raises(AccountIsolationError) as exc:
        check(TradingMode.LIVE, ledger, instances, notifier, clock)
    assert [v.asset for v in exc.value.violations] == ["SOL"]


def test_live_fails_closed_when_balance_cannot_be_read(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    freqtrade.fail = True
    with pytest.raises(IsolationCheckUnavailableError):
        check(TradingMode.LIVE, ledger, instances, notifier, clock)


def test_startup_checks_live_abort_when_ingest_fails(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    freqtrade.fail = True
    with pytest.raises(IsolationCheckUnavailableError, match="ingest failed"):
        run_startup_checks(
            mode=TradingMode.LIVE,
            ledger=ledger,
            instances=instances,
            notifier=notifier,
            principal=D(100),
            now=clock,
        )


def test_startup_checks_dry_run_does_not_touch_freqtrade(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    freqtrade.fail = True  # unreachable Freqtrade must not block a dry-run start
    run_startup_checks(
        mode=TradingMode.DRY_RUN,
        ledger=ledger,
        instances=instances,
        notifier=notifier,
        principal=D(100),
        now=clock,
    )


def test_create_app_in_live_mode_refuses_to_start_on_unexplained_balance(db_path: Path) -> None:
    ft = FakeFreqtrade(balance_by_currency={"BTC": D("1")})
    with pytest.raises(AccountIsolationError):
        create_app(
            make_settings(db_path, trading_mode="live"),
            instances=[FreqtradeInstance("primary", ft)],
        )


def test_create_app_in_live_mode_starts_when_clean(db_path: Path) -> None:
    ft = FakeFreqtrade(balance_by_currency={"USD": D(100)})
    create_app(
        make_settings(db_path, trading_mode="live"), instances=[FreqtradeInstance("primary", ft)]
    )
