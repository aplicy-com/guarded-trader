"""Freqtrade WRITE client: the entire write surface Conductor has (3A-3).

Separate from the read-only client on purpose. Every request is checked
against an explicit allowlist in the HTTP layer, so a future edit cannot
quietly add a new write:

    POST   /stopentry                       pause new entries
    POST   /start                           resume
    POST   /stop                            stop the bot
    POST   /forceexit  {"tradeid":"all","ordertype":"market"}   flatten
    DELETE /trades/{int}/open-order         cancel one trade's open order

Everything else is refused before it leaves the process: no /forceenter (the
LLM and Conductor never open positions, ADR-0003), no /reload_config or other
config writes, no /trades/{id} deletion, no blacklist edits. Note that
`/stopentry` is Freqtrade's PAUSED state, which `/start` undoes.
"""

import json
import re

import httpx
import structlog

log = structlog.get_logger()

FORCEEXIT_BODY = {"tradeid": "all", "ordertype": "market"}
_CANCEL_PATH = re.compile(r"^/api/v1/trades/[0-9]{1,12}/open-order$")
_SIMPLE = {
    ("POST", "/api/v1/stopentry"),
    ("POST", "/api/v1/start"),
    ("POST", "/api/v1/stop"),
}


class FreqtradeControlError(RuntimeError):
    """Refused by the allowlist, transport failure, or a non-2xx answer."""


def is_allowed(method: str, path: str, body: bytes) -> bool:
    if (method, path) in _SIMPLE:
        return not body
    if method == "DELETE" and _CANCEL_PATH.match(path):
        return not body
    if method == "POST" and path == "/api/v1/forceexit":
        try:
            return bool(json.loads(body) == FORCEEXIT_BODY)
        except ValueError:
            return False
    return False


def _allowlist_guard(request: httpx.Request) -> None:
    if not is_allowed(request.method, request.url.path, request.content):
        raise FreqtradeControlError(
            f"write refused by allowlist: {request.method} {request.url.path}"
        )


class FreqtradeControlClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=httpx.BasicAuth(username, password),
            timeout=timeout,
            transport=transport,
            event_hooks={"request": [_allowlist_guard]},
        )

    def close(self) -> None:
        self._http.close()

    def _send(self, method: str, path: str, json_body: dict[str, str] | None = None) -> None:
        try:
            resp = self._http.request(method, f"/api/v1{path}", json=json_body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise FreqtradeControlError(f"{method} {path} failed: {type(exc).__name__}") from exc
        log.warning("freqtrade_control_call", method=method, path=path)

    def pause_entries(self) -> None:
        self._send("POST", "/stopentry")

    def resume(self) -> None:
        self._send("POST", "/start")

    def stop(self) -> None:
        self._send("POST", "/stop")

    def cancel_open_order(self, trade_id: int) -> None:
        self._send("DELETE", f"/trades/{int(trade_id)}/open-order")

    def force_exit_all(self) -> None:
        self._send("POST", "/forceexit", dict(FORCEEXIT_BODY))
