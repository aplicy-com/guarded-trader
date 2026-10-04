from decimal import Decimal

from fastapi.testclient import TestClient

from conductor.application.fence import run_daily_fence
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.infrastructure.config import Settings
from conductor.main import create_app
from fakes import Clock, FakeFreqtrade, FakeFx, closed_view

D = Decimal


def test_capital_endpoint_is_compute_only_and_uses_strings(
    settings: Settings, clock: Clock
) -> None:
    ft = FakeFreqtrade()
    ft.closed_trades = [closed_view(1, "40")]
    inst = [FreqtradeInstance("primary", ft)]
    app = create_app(settings, instances=inst, fx=FakeFx(), clock=clock)
    run_ingest(app.state.ledger, inst, now=clock)
    run_daily_fence(
        app.state.ledger, daily_profit_cap=D(10), manual_move_threshold=D(25), now=clock
    )
    with TestClient(app) as client:
        r = client.get("/capital")
    assert r.status_code == 200
    assert r.json() == {
        "principal": "100",
        "realized_profit": "40",
        "fenced_total": "30",
        "working_profit": "10",
        "max_deployed_capital": "110",
        "enforced": False,
    }


def test_capital_after_fresh_start_is_just_the_principal(settings: Settings) -> None:
    app = create_app(
        settings, instances=[FreqtradeInstance("primary", FakeFreqtrade())], fx=FakeFx()
    )
    with TestClient(app) as client:
        body = client.get("/capital").json()
    assert body["max_deployed_capital"] == "100"
    assert body["enforced"] is False
