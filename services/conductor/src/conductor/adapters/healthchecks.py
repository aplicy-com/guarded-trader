import structlog

log = structlog.get_logger()


class LogHeartbeat:
    """Stub `Heartbeat`: logs only, makes NO network call. healthchecks.io lands in 3A-5."""

    def ping(self) -> None:
        log.info("heartbeat_stub")
