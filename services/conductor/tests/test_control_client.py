"""The Freqtrade write client: an explicit allowlist, enforced before any request is sent."""

import json

import httpx
import pytest

from conductor.adapters.freqtrade import FreqtradeControlClient, FreqtradeControlError
from conductor.adapters.freqtrade.control_client import is_allowed

FORCEEXIT = json.dumps({"tradeid": "all", "ordertype": "market"}).encode()


def make(status: int = 200) -> tuple[FreqtradeControlClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"status": "ok"})

    return FreqtradeControlClient(
        "http://ft:8080", "u", "p", transport=httpx.MockTransport(handler)
    ), seen


def test_public_surface_is_exactly_the_five_actions() -> None:
    public = {n for n in dir(FreqtradeControlClient) if not n.startswith("_")}
    assert public == {
        "pause_entries",
        "resume",
        "stop",
        "cancel_open_order",
        "force_exit_all",
        "close",
    }


def test_each_allowed_action_sends_exactly_the_documented_request() -> None:
    c, seen = make()
    c.pause_entries()
    c.resume()
    c.stop()
    c.cancel_open_order(7)
    c.force_exit_all()
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/api/v1/stopentry"),
        ("POST", "/api/v1/start"),
        ("POST", "/api/v1/stop"),
        ("DELETE", "/api/v1/trades/7/open-order"),
        ("POST", "/api/v1/forceexit"),
    ]
    assert json.loads(seen[-1].content) == {"tradeid": "all", "ordertype": "market"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/v1/forceenter", b'{"pair":"BTC/USD"}'),  # never opens positions
        ("POST", "/api/v1/forcebuy", b"{}"),
        ("POST", "/api/v1/forceenter", FORCEEXIT),  # even with an allowed body shape
        ("POST", "/api/v1/forcebuy", FORCEEXIT),
        ("POST", "/api/v1/reload_config", FORCEEXIT),
        ("POST", "/api/v1/stopentry", FORCEEXIT),
        ("DELETE", "/api/v1/forceexit", FORCEEXIT),
        ("POST", "/api/v1/reload_config", b""),  # no config writes
        ("POST", "/api/v1/pause", b""),  # only the documented alias is allowed
        ("POST", "/api/v1/stopbuy", b""),
        ("POST", "/api/v1/blacklist", b"{}"),
        ("DELETE", "/api/v1/blacklist", b""),
        ("DELETE", "/api/v1/trades/1", b""),  # deleting a trade record
        ("DELETE", "/api/v1/trades/abc/open-order", b""),
        ("DELETE", "/api/v1/trades/1/open-order/extra", b""),
        ("DELETE", "/api/v1/trades/../../forceenter/open-order", b""),
        ("POST", "/api/v1/forcesell", FORCEEXIT),  # deprecated alias is not on the list
        ("POST", "/api/v1/forceexit", b'{"tradeid":1}'),  # a single trade, not "all"
        ("POST", "/api/v1/forceexit", b'{"tradeid":"all"}'),  # must be a market exit
        ("POST", "/api/v1/forceexit", b'{"tradeid":"all","ordertype":"limit"}'),
        ("POST", "/api/v1/forceexit", b'{"tradeid":"all","ordertype":"market","price":1}'),
        ("POST", "/api/v1/forceexit", b"not json"),
        ("POST", "/api/v1/forceexit", b""),
        ("POST", "/api/v1/stopentry", b'{"x":1}'),  # no payload smuggling on simple calls
        ("GET", "/api/v1/stopentry", b""),
        ("PUT", "/api/v1/start", b""),
        ("PATCH", "/api/v1/stop", b""),
        ("POST", "/start", b""),  # wrong prefix
        ("POST", "/api/v1/start/", b""),
    ],
)
def test_everything_else_is_refused(method: str, path: str, body: bytes) -> None:
    assert is_allowed(method, path, body) is False


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/api/v1/forceenter", {"pair": "BTC/USD"}),
        ("POST", "/api/v1/reload_config", None),
        ("DELETE", "/api/v1/trades/1", None),
        ("GET", "/api/v1/status", None),
    ],
)
def test_refusal_happens_before_anything_is_sent(
    method: str, path: str, json_body: dict[str, str] | None
) -> None:
    c, seen = make()
    with pytest.raises(FreqtradeControlError, match="allowlist"):
        c._http.request(method, path, json=json_body)
    assert seen == []


def test_http_error_is_a_control_error_not_a_silent_success() -> None:
    c, _ = make(status=500)
    with pytest.raises(FreqtradeControlError, match="stopentry failed"):
        c.pause_entries()


def test_unreachable_is_a_control_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    c = FreqtradeControlClient("http://ft:8080", "u", "p", transport=httpx.MockTransport(boom))
    with pytest.raises(FreqtradeControlError):
        c.resume()


def test_cancel_open_order_coerces_to_int() -> None:
    c, seen = make()
    c.cancel_open_order(int("12"))
    assert seen[0].url.path == "/api/v1/trades/12/open-order"
