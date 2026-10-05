"""Telegram alerts: a sync sender and a non-blocking, deduping notifier.

Outbound HTTPS only (sendMessage). The alert path is deliberately independent of
the command bot (adapters/telegram_bot.py) and can never block or crash a
caller: `send` enqueues and returns; a daemon thread delivers; every failure is
logged and dropped. The bot token appears only in the request URL and is
redacted from logs (infrastructure/logging.py).
"""

import contextlib
import queue
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol

import httpx
import structlog

from conductor.domain.alert_policy import AlertPolicy

log = structlog.get_logger()

MAX_MESSAGE_CHARS = 4000  # Telegram's hard limit is 4096
QUEUE_SIZE = 100


class LogNotifier:
    """`Notifier` used when Telegram is not configured: logs only."""

    def send(self, text: str) -> None:
        log.info("notify_stub", text=text)


class TelegramError(RuntimeError):
    """Message never includes the URL (it contains the token)."""


class MessageSender(Protocol):
    def send_message(self, chat_id: int, text: str) -> None: ...


class TelegramApi:
    def __init__(
        self,
        token: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self._http = httpx.Client(
            base_url=f"{base_url}/bot{token}", timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def send_message(self, chat_id: int, text: str) -> None:
        try:
            resp = self._http.post(
                "/sendMessage",
                json={"chat_id": chat_id, "text": text[:MAX_MESSAGE_CHARS]},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TelegramError(f"sendMessage HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise TelegramError(f"sendMessage failed: {type(exc).__name__}") from None


class TelegramAlertNotifier:
    """`Notifier` that delivers to every allow-listed chat. Never raises, never blocks."""

    def __init__(
        self,
        sender: MessageSender,
        chat_ids: Sequence[int],
        *,
        policy: AlertPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sender = sender
        self._chat_ids = tuple(chat_ids)
        self._policy = policy or AlertPolicy()
        self._clock = clock
        self._lock = threading.Lock()
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=QUEUE_SIZE)
        self._worker = threading.Thread(target=self._run, name="telegram-alerts", daemon=True)
        self._worker.start()

    def send(self, text: str) -> None:
        try:
            with self._lock:
                decision = self._policy.admit(text, self._clock())
            if not decision.send:
                return
            self._queue.put_nowait(decision.prefix + text)
        except queue.Full:
            log.error("alert_queue_full_dropped")
        except Exception:
            log.exception("alert_enqueue_failed")

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                for chat_id in self._chat_ids:
                    try:
                        self._sender.send_message(chat_id, item)
                    except Exception as exc:
                        log.error("alert_delivery_failed", chat_id=chat_id, error=str(exc)[:120])
            finally:
                self._queue.task_done()

    def flush(self, timeout: float = 5.0) -> None:
        """Wait for queued alerts (tests, shutdown)."""
        done = threading.Event()

        def wait_then_signal() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=wait_then_signal, daemon=True).start()
        done.wait(timeout)

    def close(self) -> None:
        self.flush()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)
        self._worker.join(timeout=2)
