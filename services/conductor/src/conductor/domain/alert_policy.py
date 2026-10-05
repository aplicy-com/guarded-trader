"""Alert dedupe and rate limiting. Pure; no I/O.

Identical text inside `dedupe_seconds` is dropped. At most `max_per_window`
messages are admitted per `window_seconds`; the overflow is counted and
reported once as a "suppressed" summary on the next admitted alert, so a storm
cannot flood the chat but is never invisible.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class Decision:
    send: bool
    prefix: str = ""  # e.g. "(3 alerts suppressed)\n", prepended to the next message


class AlertPolicy:
    def __init__(
        self, *, dedupe_seconds: int = 300, max_per_window: int = 10, window_seconds: int = 60
    ) -> None:
        if max_per_window < 1 or window_seconds < 1 or dedupe_seconds < 0:
            raise ValueError("invalid alert policy")
        self._dedupe = timedelta(seconds=dedupe_seconds)
        self._max = max_per_window
        self._window = timedelta(seconds=window_seconds)
        self._last_seen: dict[str, datetime] = {}
        self._sent: list[datetime] = []
        self._suppressed = 0

    def admit(self, text: str, now: datetime) -> Decision:
        seen = self._last_seen.get(text)
        if seen is not None and now - seen < self._dedupe:
            return Decision(False)
        self._sent = [t for t in self._sent if now - t < self._window]
        if len(self._sent) >= self._max:
            self._suppressed += 1
            return Decision(False)
        self._last_seen[text] = now
        self._sent.append(now)
        self._forget_old(now)
        prefix = ""
        if self._suppressed:
            prefix = f"({self._suppressed} alert(s) suppressed by rate limit)\n"
            self._suppressed = 0
        return Decision(True, prefix)

    def _forget_old(self, now: datetime) -> None:
        if len(self._last_seen) > 500:
            self._last_seen = {k: v for k, v in self._last_seen.items() if now - v < self._dedupe}
