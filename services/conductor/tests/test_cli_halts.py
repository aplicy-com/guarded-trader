"""Operator CLI for halts."""

import sqlite3
from pathlib import Path

import pytest

from conductor import cli
from conductor.application.ingest import FreqtradeInstance
from conductor.application.principal import ensure_principal
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, open_view


@pytest.fixture(autouse=True)
def env(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ledger: SqliteLedger,
    clock: Clock,
    notifier: RecordingNotifier,
    freqtrade: FakeFreqtrade,
) -> None:
    from decimal import Decimal

    for k, v in {
        "PRINCIPAL_USD": "100",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "FREQTRADE__API_SERVER__USERNAME": "u",
        "FREQTRADE__API_SERVER__PASSWORD": "p",
    }.items():
        monkeypatch.setenv(k, v)
    ensure_principal(ledger, Decimal(100), notifier=notifier, now=clock)
    monkeypatch.setattr(
        cli,
        "build_instances",
        lambda _s: ([FreqtradeInstance("primary", freqtrade, freqtrade)], []),
    )


def test_kill_halts_clear_roundtrip(
    freqtrade: FakeFreqtrade, capsys: pytest.CaptureFixture[str], db_path: Path
) -> None:
    assert cli.main(["kill", "--operator", "maduka"]) == 0
    assert freqtrade.state == "paused"
    assert "engaged" in capsys.readouterr().out
    assert cli.main(["halts"]) == 0
    out = capsys.readouterr().out
    assert "#1 kill_switch" in out
    assert "ACTIVE" in out
    assert cli.main(["clear-halt", "1", "--operator", "maduka", "--note", "ok"]) == 0
    assert freqtrade.state == "running"
    assert cli.main(["halts"]) == 0
    assert "no active halts" in capsys.readouterr().out
    assert sqlite3.connect(db_path).execute("SELECT operator FROM halt_clears").fetchall() == [
        ("maduka",)
    ]


def test_operator_is_mandatory() -> None:
    with pytest.raises(SystemExit):
        cli.main(["kill"])
    with pytest.raises(SystemExit):
        cli.main(["clear-halt", "1"])


def test_nuclear_needs_explicit_confirmation(
    freqtrade: FakeFreqtrade, capsys: pytest.CaptureFixture[str]
) -> None:
    freqtrade.open_trades = [open_view(1)]
    assert cli.main(["nuclear", "--operator", "maduka"]) == 1
    assert "--confirm-flatten-everything" in capsys.readouterr().err
    assert freqtrade.control_calls == []
    assert len(freqtrade.open_trades) == 1


def test_nuclear_flattens_and_stops(
    freqtrade: FakeFreqtrade, capsys: pytest.CaptureFixture[str]
) -> None:
    freqtrade.open_trades = [open_view(1)]
    assert cli.main(["nuclear", "--operator", "maduka", "--confirm-flatten-everything"]) == 0
    assert freqtrade.state == "stopped"
    assert freqtrade.open_trades == []
    assert "force_exit_all: ok" in capsys.readouterr().out


def test_failed_steps_exit_nonzero_and_say_what_to_do(
    freqtrade: FakeFreqtrade, capsys: pytest.CaptureFixture[str]
) -> None:
    freqtrade.fail = True
    assert cli.main(["kill", "--operator", "maduka"]) == 1
    cap = capsys.readouterr()
    assert "FAILED" in cap.out
    assert "re-applied" in cap.err


def test_clear_unknown_halt_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["clear-halt", "42", "--operator", "maduka"]) == 1
    assert "no halt" in capsys.readouterr().err
