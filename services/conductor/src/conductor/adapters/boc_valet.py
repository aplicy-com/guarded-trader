"""Bank of Canada Valet API: daily USD/CAD (series FXUSDCAD). Read-only HTTP GET.

The Bank publishes one rate per Canadian business day, so a weekend/holiday
resolves to the most recent earlier publication (looked back up to 10 days).
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
import structlog

from conductor.application.ledger_ports import FxUnavailableError
from conductor.domain.tax import FxRate

log = structlog.get_logger()

BASE_URL = "https://www.bankofcanada.ca/valet"
SERIES = "FXUSDCAD"
SOURCE = "BankOfCanada"
LOOKBACK_DAYS = 10


class BankOfCanadaFx:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def usd_cad(self, on: date) -> FxRate:
        params = {
            "start_date": (on - timedelta(days=LOOKBACK_DAYS)).isoformat(),
            "end_date": on.isoformat(),
        }
        try:
            resp = self._http.get(f"/observations/{SERIES}/json", params=params)
            resp.raise_for_status()
            payload = resp.json()
            best: tuple[date, Decimal] | None = None
            for obs in payload["observations"]:
                d = date.fromisoformat(obs["d"])
                rate = Decimal(str(obs[SERIES]["v"]))
                if d <= on and rate.is_finite() and rate > 0 and (best is None or d > best[0]):
                    best = (d, rate)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
            raise FxUnavailableError(f"Bank of Canada rate for {on}: {type(exc).__name__}") from exc
        if best is None:
            raise FxUnavailableError(
                f"no Bank of Canada rate published in the {LOOKBACK_DAYS} days to {on}"
            )
        return FxRate(requested_date=on, rate_date=best[0], rate=best[1], source=SOURCE)
