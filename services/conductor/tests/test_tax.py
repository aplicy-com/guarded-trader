"""NFR6: CAD valuation use case, FX cache, Bank of Canada adapter, CSV export."""

import csv
import io
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from conductor.adapters.boc_valet import BankOfCanadaFx
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.ledger_ports import FxUnavailableError
from conductor.application.principal import ensure_principal
from conductor.application.tax import CSV_COLUMNS, export_tax_csv, value_closed_trades
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, FakeFx, RecordingNotifier, closed_view

D = Decimal
FIXTURE = Path(__file__).parent / "fixtures" / "boc" / "fxusdcad_2026-09-10_to_15.json"


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)


def ingest(ledger: SqliteLedger, clock: Clock, *trades: object) -> None:
    ft = FakeFreqtrade()
    ft.closed_trades = list(trades)  # type: ignore[arg-type]
    run_ingest(ledger, [FreqtradeInstance("primary", ft)], now=clock)


# open Fri 2026-09-11, close Mon 2026-09-14 (closed_view defaults)


def test_values_closed_trade_and_is_idempotent(
    ledger: SqliteLedger, clock: Clock, fx: FakeFx, db_path: Path
) -> None:
    ingest(ledger, clock, closed_view(1, "2.00"))
    r = value_closed_trades(ledger, fx, now=clock)
    assert (r.valued, r.pending, r.failed) == (1, 0, 0)
    row = (
        sqlite3.connect(db_path)
        .execute(
            "SELECT cost_usd, net_proceeds_usd, open_usd_cad, cost_cad, proceeds_cad, gain_cad"
            " FROM trade_cad_valuations"
        )
        .fetchone()
    )
    assert row == ("33.05", "35.05", "1.40", "46.27", "49.07", "2.80")
    again = value_closed_trades(ledger, fx, now=clock)
    assert (again.valued, again.pending, again.failed) == (0, 0, 0)


def test_trade_closed_today_is_pending_until_the_utc_day_ends(
    ledger: SqliteLedger, clock: Clock, fx: FakeFx
) -> None:
    ingest(ledger, clock, closed_view(1, close_date=datetime(2026, 10, 4, 3, tzinfo=UTC)))
    assert value_closed_trades(ledger, fx, now=clock).pending == 1
    assert fx.calls == []
    clock.at += timedelta(days=1)
    assert value_closed_trades(ledger, fx, now=clock).valued == 1


def test_fx_rates_are_cached_in_the_database(
    ledger: SqliteLedger, clock: Clock, fx: FakeFx, db_path: Path
) -> None:
    ingest(ledger, clock, closed_view(1), closed_view(2), closed_view(3))
    value_closed_trades(ledger, fx, now=clock)
    assert sorted(fx.calls) == [date(2026, 9, 11), date(2026, 9, 14)]  # one fetch per distinct day
    ingest(ledger, clock, closed_view(1), closed_view(2), closed_view(3), closed_view(4))
    fx.calls.clear()
    value_closed_trades(ledger, fx, now=clock)  # new trade, same days -> served from the DB
    assert fx.calls == []
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM fx_rates").fetchone() == (2,)


def test_weekend_close_uses_prior_business_day_rate(
    ledger: SqliteLedger, clock: Clock, fx: FakeFx, db_path: Path
) -> None:
    ingest(
        ledger, clock, closed_view(1, close_date=datetime(2026, 9, 13, 10, tzinfo=UTC))
    )  # Sunday
    value_closed_trades(ledger, fx, now=clock)
    assert sqlite3.connect(db_path).execute(
        "SELECT close_fx_date FROM trade_cad_valuations"
    ).fetchone() == ("2026-09-11",)


def test_fx_outage_leaves_trade_unvalued_then_retries(
    ledger: SqliteLedger, clock: Clock, fx: FakeFx, db_path: Path
) -> None:
    ingest(ledger, clock, closed_view(1))
    fx.unavailable = True
    assert value_closed_trades(ledger, fx, now=clock).failed == 1
    assert sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM trade_cad_valuations"
    ).fetchone() == (0,)
    fx.unavailable = False
    assert value_closed_trades(ledger, fx, now=clock).valued == 1


def test_incomplete_trade_is_never_guessed(ledger: SqliteLedger, clock: Clock, fx: FakeFx) -> None:
    ingest(ledger, clock, closed_view(1, fee_open_cost=None))
    r = value_closed_trades(ledger, fx, now=clock)
    assert (r.valued, r.failed) == (0, 1)


def test_export_csv_columns_rows_and_formula_neutralisation(
    ledger: SqliteLedger, clock: Clock, fx: FakeFx
) -> None:
    ingest(
        ledger,
        clock,
        closed_view(1, "2.00"),
        closed_view(2, "-1.00", exit_reason="=cmd|' /C calc'!A0"),
    )
    value_closed_trades(ledger, fx, now=clock)
    out = io.StringIO()
    assert export_tax_csv(ledger, out) == 2
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert tuple(rows[0]) == CSV_COLUMNS
    first = next(r for r in rows if r["trade_id"] == "1")
    assert (first["cost_cad"], first["proceeds_cad"], first["gain_cad"]) == (
        "46.27",
        "49.07",
        "2.80",
    )
    assert (first["profit_usd"], first["open_usd_cad"], first["fx_source"]) == (
        "2.00",
        "1.40",
        "BankOfCanada",
    )
    assert first["close_date_utc"].endswith("+00:00")
    second = next(r for r in rows if r["trade_id"] == "2")
    assert second["exit_reason"].startswith("'=")
    assert second["gain_cad"] == "-1.40"


def test_export_with_nothing_valued_is_header_only(ledger: SqliteLedger) -> None:
    out = io.StringIO()
    assert export_tax_csv(ledger, out) == 0
    assert out.getvalue().strip().split(",") == list(CSV_COLUMNS)


# ---- Bank of Canada adapter ---------------------------------------------------


def boc(handler: httpx.MockTransport | None = None, body: object | None = None) -> BankOfCanadaFx:
    payload = body if body is not None else json.loads(FIXTURE.read_text())
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    client = BankOfCanadaFx(transport=handler or httpx.MockTransport(respond))
    client.requests = seen  # type: ignore[attr-defined]
    return client


def test_boc_exact_business_day() -> None:
    fx = boc().usd_cad(date(2026, 9, 11))
    assert (fx.rate_date, fx.rate, fx.source) == (date(2026, 9, 11), D("1.3866"), "BankOfCanada")


@pytest.mark.parametrize("day", [date(2026, 9, 12), date(2026, 9, 13)])
def test_boc_weekend_resolves_to_previous_publication(day: date) -> None:
    fx = boc().usd_cad(day)
    assert (fx.requested_date, fx.rate_date, fx.rate) == (day, date(2026, 9, 11), D("1.3866"))


def test_boc_never_uses_a_later_observation() -> None:
    fx = boc().usd_cad(date(2026, 9, 11))
    assert fx.rate_date <= fx.requested_date


def test_boc_request_shape_is_a_get_with_a_bounded_window() -> None:
    client = boc()
    client.usd_cad(date(2026, 9, 14))
    (req,) = client.requests  # type: ignore[attr-defined]
    assert req.method == "GET"
    assert req.url.path == "/valet/observations/FXUSDCAD/json"
    assert dict(req.url.params) == {"start_date": "2026-09-04", "end_date": "2026-09-14"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"observations": []},
        {"observations": [{"d": "2026-09-11", "FXUSDCAD": {"v": "abc"}}]},
        {"observations": [{"d": "2026-09-11", "FXUSDCAD": {"v": "0"}}]},
        {"observations": [{"d": "2026-09-20", "FXUSDCAD": {"v": "1.3"}}]},
    ],
)
def test_boc_malformed_or_empty_is_unavailable(body: object) -> None:
    with pytest.raises(FxUnavailableError):
        boc(body=body).usd_cad(date(2026, 9, 11))


def test_boc_http_error_is_unavailable() -> None:
    client = boc(httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(FxUnavailableError):
        client.usd_cad(date(2026, 9, 11))
