"""Best-effort alert sending. Risk logic must never depend on, or be blocked by, Telegram."""

import structlog

from conductor.application.ports import Notifier

log = structlog.get_logger()


def safe_send(notifier: Notifier | None, text: str) -> None:
    """Send an alert; swallow and log any failure. A broken notifier is not an incident
    for the code that called it."""
    if notifier is None:
        return
    try:
        notifier.send(text)
    except Exception:
        log.exception("alert_failed")
