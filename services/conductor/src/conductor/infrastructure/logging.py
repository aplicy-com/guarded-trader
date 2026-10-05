import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

# Telegram puts the bot token in the URL path (".../bot<id>:<secret>/method"), and
# libraries sometimes echo URLs in messages and tracebacks. Redact it everywhere.
_BOT_TOKEN = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}")


def redact(text: str) -> str:
    return _BOT_TOKEN.sub("bot<redacted>", text)


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def _redact_event(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact(value)
    return event_dict


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    """structlog -> stdout; JSON in containers, console renderer for humans."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RedactingFilter())
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    # httpx logs every request URL at INFO: for Telegram that URL contains the token.
    # botocore at DEBUG logs request headers (key id, signature) and URLs; keep it quiet always.
    for noisy in ("httpx", "httpcore", "hpack", "boto3", "botocore", "s3transfer", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _redact_event,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=False,
    )
