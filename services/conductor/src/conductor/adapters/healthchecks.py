"""Heartbeat adapters: healthchecks.io (push) and a log-only stub."""

import httpx
import structlog

log = structlog.get_logger()

PING_TIMEOUT_SECONDS = 10.0
PING_ATTEMPTS = 2


class HeartbeatDeliveryError(RuntimeError):
    """A ping did not get through. The message never contains the ping URL (it embeds the
    check's UUID, which is a secret)."""


class LogHeartbeat:
    """Log-only `Heartbeat`: makes NO network call. Used when no ping URL is configured."""

    def ok(self) -> None:
        log.info("heartbeat_stub", outcome="ok")

    def fail(self, reason: str) -> None:
        log.info("heartbeat_stub", outcome="fail", reason=reason)


class HealthchecksHeartbeat:
    """healthchecks.io pings. ``url`` is the check's ping URL; failures go to ``<url>/fail``
    with the reason as the request body (shown in the alert). Outbound only."""

    def __init__(self, url: str, client: httpx.Client) -> None:
        self._url = url.rstrip("/")
        self._client = client

    def ok(self) -> None:
        self._send(self._url, b"")

    def fail(self, reason: str) -> None:
        self._send(f"{self._url}/fail", reason.encode("utf-8", "replace")[:1000])

    def _send(self, url: str, body: bytes) -> None:
        last = "no attempt"
        for _ in range(PING_ATTEMPTS):
            try:
                response = self._client.post(url, content=body, timeout=PING_TIMEOUT_SECONDS)
            except httpx.HTTPError as exc:
                # Class name only: an httpx message can carry the URL.
                last = type(exc).__name__
                continue
            if response.status_code < 300:
                return
            last = f"HTTP {response.status_code}"
        raise HeartbeatDeliveryError(f"healthchecks ping failed: {last}")
