"""Contract tests: client vs. fixtures (see tests/fixtures/freqtrade/README.md)."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from conductor.adapters.freqtrade import FreqtradeApiError, FreqtradeRestClient

ROUTES = {
    "/api/v1/ping": "ping",
    "/api/v1/show_config": "show_config",
    "/api/v1/status": "status",
    "/api/v1/trades": "trades",
    "/api/v1/profit": "profit",
}


def make_client(
    fixture_json: Callable[[str], Any], seen: list[httpx.Request] | None = None, **overrides: Any
) -> FreqtradeRestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        name = overrides.get(request.url.path) or ROUTES.get(request.url.path)
        if name is None:
            return httpx.Response(404)
        if isinstance(name, httpx.Response):
            return name
        return httpx.Response(200, json=fixture_json(name))

    return FreqtradeRestClient(
        "http://freqtrade:8080", "u", "p", transport=httpx.MockTransport(handler)
    )


def test_ping(fixture_json: Callable[[str], Any]) -> None:
    assert make_client(fixture_json).ping() is True


def test_ping_is_false_not_an_exception_when_unreachable(
    fixture_json: Callable[[str], Any],
) -> None:
    c = make_client(fixture_json, **{"/api/v1/ping": httpx.Response(500)})
    assert c.ping() is False


def test_show_config(fixture_json: Callable[[str], Any]) -> None:
    cfg = make_client(fixture_json).show_config()
    assert (cfg.bot_name, cfg.version, cfg.strategy) == (
        "ai-trading-agent-dryrun",
        "2026.8",
        "Baseline4h",
    )
    assert cfg.dry_run is True
    assert cfg.stake_amount == "unlimited"
    assert (cfg.max_open_trades, cfg.timeframe, cfg.exchange) == (3, "4h", "kraken")


def test_status_maps_open_trades_with_decimal_money(fixture_json: Callable[[str], Any]) -> None:
    trades = make_client(fixture_json).status()
    assert [t.pair for t in trades] == ["LTC/USD", "SOL/USD", "BTC/USD"]
    ltc = trades[0]
    assert ltc.is_short is False
    assert ltc.open_rate == Decimal("55.16")
    assert ltc.stake_amount == Decimal("31.99739593")  # floats must not leak binary noise
    assert ltc.profit_abs == Decimal("8.86293062")
    assert ltc.open_date == datetime(2026, 9, 18, 8, 0, 9, 574000, tzinfo=UTC)


def test_status_empty(fixture_json: Callable[[str], Any]) -> None:
    c = make_client(fixture_json, **{"/api/v1/status": "status_empty"})
    assert c.status() == ()


def test_trades_closed_page(fixture_json: Callable[[str], Any]) -> None:
    page = make_client(fixture_json).trades(limit=50)
    assert (page.trades_count, page.total_trades, page.offset) == (2, 2, 0)
    eth, xrp = page.trades
    assert (eth.pair, eth.is_open) == ("ETH/USD", False)
    assert eth.close_date is not None and eth.close_date > eth.open_date
    assert eth.close_profit_abs == Decimal("-1.36936162")
    assert eth.close_profit_ratio == Decimal("-0.04142954513193126")
    assert eth.exit_reason == "trailing_stop_loss"
    assert xrp.close_rate == Decimal("1.35606")


def test_trades_open_trade_has_no_close_fields(fixture_json: Callable[[str], Any]) -> None:
    payload = fixture_json("trades")
    for key in ("close_timestamp", "close_rate", "close_profit", "close_profit_abs", "exit_reason"):
        payload["trades"][0][key] = None
    payload["trades"][0]["is_open"] = True
    c = make_client(fixture_json, **{"/api/v1/trades": httpx.Response(200, json=payload)})
    t = c.trades().trades[0]
    assert t.is_open and t.close_date is None and t.close_rate is None and t.exit_reason is None


def test_trades_sends_pagination_params(fixture_json: Callable[[str], Any]) -> None:
    seen: list[httpx.Request] = []
    make_client(fixture_json, seen).trades(limit=25, offset=50)
    assert dict(seen[0].url.params) == {"limit": "25", "offset": "50"}


def test_profit(fixture_json: Callable[[str], Any]) -> None:
    p = make_client(fixture_json).profit()
    assert p.closed_profit_abs == Decimal("-3.03819294")
    assert p.closed_profit_ratio == Decimal("-0.030688817575757577")
    assert (p.trade_count, p.closed_trade_count, p.winning_trades, p.losing_trades) == (5, 2, 0, 2)
    assert p.max_drawdown_abs == Decimal("3.03819294")


def test_contract_violation_is_a_clear_error(fixture_json: Callable[[str], Any]) -> None:
    bad = fixture_json("profit")
    del bad["profit_closed_coin"]
    c = make_client(fixture_json, **{"/api/v1/profit": httpx.Response(200, json=bad)})
    with pytest.raises(FreqtradeApiError, match="profit_closed_coin"):
        c.profit()


def test_http_error_is_wrapped(fixture_json: Callable[[str], Any]) -> None:
    c = make_client(fixture_json, **{"/api/v1/status": httpx.Response(401)})
    with pytest.raises(FreqtradeApiError):
        c.status()


def test_only_get_requests_are_ever_sent(fixture_json: Callable[[str], Any]) -> None:
    seen: list[httpx.Request] = []
    c = make_client(fixture_json, seen)
    c.ping(), c.show_config(), c.status(), c.trades(), c.profit()
    assert {r.method for r in seen} == {"GET"}
    assert all(r.headers["authorization"].startswith("Basic ") for r in seen)


def test_client_refuses_non_get(fixture_json: Callable[[str], Any]) -> None:
    c = make_client(fixture_json)
    with pytest.raises(FreqtradeApiError, match="read-only"):
        c._http.post("/forceexit", json={"tradeid": "1"})


def test_public_surface_is_read_only() -> None:
    public = {n for n in dir(FreqtradeRestClient) if not n.startswith("_")}
    assert public == {
        "ping",
        "show_config",
        "status",
        "trades",
        "profit",
        "balances",
        "whitelist",
        "close",
    }


def test_balances_sums_per_currency(fixture_json: Callable[[str], Any]) -> None:
    c = make_client(fixture_json, **{"/api/v1/balance": "balance"})
    b = c.balances()
    assert b == {"USD": Decimal("100.0")}
    assert all(isinstance(v, Decimal) for v in b.values())


def test_whitelist(fixture_json: Callable[[str], Any]) -> None:
    c = make_client(fixture_json, **{"/api/v1/whitelist": "whitelist"})
    assert c.whitelist() == (
        "BTC/USD",
        "XRP/USD",
        "ETH/USD",
        "SOL/USD",
        "LINK/USD",
        "LTC/USD",
    )


def test_balance_contract_violation_is_an_api_error() -> None:
    c = FreqtradeRestClient(
        "http://f:8080",
        "u",
        "p",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"currencies": [{"currency": "ETH"}]})
        ),
    )
    with pytest.raises(FreqtradeApiError, match="contract"):
        c.balances()
