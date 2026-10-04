import structlog

log = structlog.get_logger()


class LogNotifier:
    """Stub `Notifier`: logs instead of sending. The Telegram bot lands in 3A-4."""

    def send(self, text: str) -> None:
        log.info("notify_stub", text=text)
