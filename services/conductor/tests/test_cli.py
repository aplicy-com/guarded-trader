"""Internal operator CLI."""

import csv
import io
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from conductor import cli
from conductor.application.fence import run_daily_fence
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.principal import ensure_principal
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, closed_view

D = Decimal


@pytest.fixture(autouse=True)
def env(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {
        "PRINCIPAL_USD": "100",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "FREQTRADE__API_SERVER__USERNAME": "u",
        "FREQTRADE__API_SERVER__PASSWORD": "p",
    }.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def funded(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)
    ft = FakeFreqtrade()
    ft.closed_trades = [closed_view(1, "40")]
    run_ingest(ledger, [FreqtradeInstance("primary", ft)], now=clock)
    run_daily_fence(ledger, daily_profit_cap=D(10), manual_move_threshold=D(25), now=clock)


def test_capital_prints_the_r2_numbers(funded: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["capital"]) == 0
    out = capsys.readouterr().out
    assert "max_deployed_capital: 110" in out
    assert "fenced_total: 30" in out


def test_record_transfer_happy_path_and_overdraw(
    funded: None, db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    base = [
        "record-transfer",
        "--destination",
        "hw wallet",
        "--tx-id",
        "T1",
        "--operator",
        "maduka",
        "--at",
        at,
    ]
    assert cli.main([*base, "--amount", "20"]) == 0
    assert "recorded transfer of 20" in capsys.readouterr().out
    assert sqlite3.connect(db_path).execute(
        "SELECT amount, operator FROM manual_transfers"
    ).fetchall() == [("20", "maduka")]
    assert cli.main([*base[:4], "T2", *base[5:], "--amount", "20"]) == 1  # only 10 left
    assert "exceeds" in capsys.readouterr().err


def test_record_transfer_rejects_naive_timestamp_and_bad_amount(
    funded: None, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["record-transfer", "--destination", "d", "--tx-id", "T", "--operator", "o"]
    with pytest.raises(SystemExit):
        cli.main([*common, "--amount", "5", "--at", "2026-10-04T12:00:00"])
    with pytest.raises(SystemExit):
        cli.main([*common, "--amount", "NaN"])
    assert "timezone" in capsys.readouterr().err


def test_export_tax_to_stdout_is_csv_and_progress_goes_to_stderr(
    funded: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["export-tax"]) == 0
    cap = capsys.readouterr()
    assert next(csv.reader(io.StringIO(cap.out)))[0] == "instance"
    assert "exported 0 trade(s)" in cap.err


def test_export_tax_to_file(funded: None, tmp_path: Path) -> None:
    out = tmp_path / "tax.csv"
    assert cli.main(["export-tax", "--out", str(out)]) == 0
    assert out.read_text().startswith("instance,trade_id")


def test_missing_config_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL")
    assert cli.main(["capital"]) == 2
    assert "CONFIG ERROR: database_url" in capsys.readouterr().err
