"""Tracks how long each Freqtrade instance has been unreachable (alert after N minutes)."""

from datetime import datetime, timedelta

DOWN_ALERT_AFTER = timedelta(minutes=10)


class ReachabilityTracker:
    """In-memory; a Conductor restart restarts the clock (acceptable for an alert)."""

    def __init__(self, alert_after: timedelta = DOWN_ALERT_AFTER) -> None:
        self._after = alert_after
        self._down_since: dict[str, datetime] = {}
        self._alerted: set[str] = set()

    def update(self, instance: str, reachable: bool, now: datetime) -> str | None:
        """Returns alert text exactly once per outage (and once on recovery), else None."""
        if reachable:
            self._down_since.pop(instance, None)
            if instance in self._alerted:
                self._alerted.discard(instance)
                return f"Freqtrade '{instance}' is reachable again."
            return None
        since = self._down_since.setdefault(instance, now)
        if instance not in self._alerted and now - since >= self._after:
            self._alerted.add(instance)
            minutes = int((now - since).total_seconds() // 60)
            return f"Freqtrade '{instance}' has been unreachable for {minutes} min."
        return None
