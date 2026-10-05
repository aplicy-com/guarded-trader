"""R1: principal set once from config; any later mismatch refuses to start."""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from conductor.application.ingest import FreqtradeInstance
from conductor.application.principal import ensure_principal
from conductor.domain.capital import PrincipalMismatchError
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.main import STARTUP_REFUSALS, app_factory, create_app
from conftest import make_settings
from fakes import Clock, FakeFreqtrade, FakeFx, RecordingNotifier

D = Decimal


def test_first_run_records_principal_and_audits(
    ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier
) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)
    with ledger.transaction(write=False) as repo:
        assert repo.get_principal() == D(100)
    assert notifier.sent == []


def test_restart_with_same_value_is_a_noop(
    ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier, db_path: Path
) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)
    clock.at = datetime(2026, 11, 1, tzinfo=UTC)
    # a brand-new engine, as after a process restart; same number, different scale
    restarted = SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))
    ensure_principal(restarted, D("100.00"), notifier=notifier, now=clock)
    rows = sqlite3.connect(db_path).execute("SELECT amount, set_at FROM principal").fetchall()
    assert rows == [("100", "2026-10-04T12:00:00.000000+00:00")]  # untouched
    assert sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM audit_log WHERE action='principal_set'"
    ).fetchone() == (1,)


@pytest.mark.parametrize("changed", [D(200), D("99.99"), D(50)])
def test_mismatch_alerts_audits_raises_and_never_overwrites(
    ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier, db_path: Path, changed: Decimal
) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)
    with pytest.raises(PrincipalMismatchError):
        ensure_principal(ledger, changed, notifier=notifier, now=clock)
    assert len(notifier.sent) == 1
    assert "R1" in notifier.sent[0]
    with ledger.transaction(write=False) as repo:
        assert repo.get_principal() == D(100)
    assert sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM audit_log WHERE action='principal_mismatch'"
    ).fetchone() == (1,)


def test_failing_notifier_does_not_mask_the_refusal(ledger: SqliteLedger, clock: Clock) -> None:
    class Broken:
        def send(self, text: str) -> None:
            raise RuntimeError("telegram down")

    ensure_principal(ledger, D(100), notifier=RecordingNotifier(), now=clock)
    with pytest.raises(PrincipalMismatchError):
        ensure_principal(ledger, D(1), notifier=Broken(), now=clock)


def _create(db: Path, principal: str) -> object:
    return create_app(
        make_settings(db, principal_usd=principal),
        instances=[FreqtradeInstance("primary", FakeFreqtrade())],
        fx=FakeFx(),
    )


def test_create_app_refuses_to_start_on_principal_mismatch(db_path: Path) -> None:
    _create(db_path, "100")
    _create(db_path, "100")  # restart: fine
    with pytest.raises(PrincipalMismatchError):
        _create(db_path, "250")


def test_app_factory_exits_nonzero_with_clear_message(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "FREQTRADE__API_SERVER__USERNAME": "u",
        "FREQTRADE__API_SERVER__PASSWORD": "p",
        "SCHEDULER_ENABLED": "false",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PRINCIPAL_USD", "100")
    app_factory()  # first run records it (real clients are constructed but never called in dry_run)
    monkeypatch.setenv("PRINCIPAL_USD", "300")
    with pytest.raises(SystemExit) as exc:
        app_factory()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "STARTUP REFUSED" in err
    assert "300" in err


def test_startup_refusals_cover_the_safety_exceptions() -> None:
    names = {e.__name__ for e in STARTUP_REFUSALS}
    assert names == {
        "PrincipalMismatchError",
        "AccountIsolationError",
        "IsolationCheckUnavailableError",
        "ModeMismatchError",
    }
