"""Read-only Freqtrade REST client.

Exposes GET-only calls: ping, show_config, status, trades, profit. There is no
method that can change state, and the HTTP layer refuses any non-GET request,
so a future edit cannot quietly turn a "reader" into an order path (ADR-0003).
Control actions (stopentry, forceexit, reload_config) are NOT here; they land
in 3A-2/3A-3 as a separate, reviewed adapter.
"""

from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from conductor.domain.freqtrade_view import (
    BotConfigView,
    OpenTradeView,
    ProfitSummary,
    TradesPage,
)

from .schemas import OpenTradeWire, PingWire, ProfitWire, ShowConfigWire, TradesWire

log = structlog.get_logger()


class FreqtradeApiError(RuntimeError):
    """Transport error, non-2xx status, or a response that does not match the contract."""


def _read_only_guard(request: httpx.Request) -> None:
    if request.method != "GET":
        raise FreqtradeApiError(f"read-only client refused {request.method} {request.url.path}")


class FreqtradeRestClient:
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
            base_url=base_url.rstrip("/") + "/api/v1",
            auth=httpx.BasicAuth(username, password),
            timeout=timeout,
            transport=transport,
            event_hooks={"request": [_read_only_guard]},
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            resp = self._http.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise FreqtradeApiError(f"GET {path} failed: {type(exc).__name__}") from exc
        except ValueError as exc:
            raise FreqtradeApiError(f"GET {path} returned non-JSON") from exc

    def _parse[T: BaseModel](self, model: type[T], path: str, payload: Any) -> T:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise FreqtradeApiError(
                f"GET {path} response violates contract: {exc.error_count()} error(s): "
                + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors())
            ) from exc

    def ping(self) -> bool:
        """True iff the bot answers `pong`. Never raises: it is a liveness probe."""
        try:
            return self._parse(PingWire, "/ping", self._get("/ping")).status == "pong"
        except FreqtradeApiError:
            return False

    def show_config(self) -> BotConfigView:
        return self._parse(ShowConfigWire, "/show_config", self._get("/show_config")).to_view()

    def status(self) -> tuple[OpenTradeView, ...]:
        payload = self._get("/status")
        if not isinstance(payload, list):
            raise FreqtradeApiError("GET /status response violates contract: expected a list")
        return tuple(self._parse(OpenTradeWire, "/status", item).to_view() for item in payload)

    def trades(self, *, limit: int = 500, offset: int = 0) -> TradesPage:
        payload = self._get("/trades", {"limit": limit, "offset": offset})
        return self._parse(TradesWire, "/trades", payload).to_view()

    def profit(self) -> ProfitSummary:
        return self._parse(ProfitWire, "/profit", self._get("/profit")).to_view()
