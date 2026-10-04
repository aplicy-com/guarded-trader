from conductor.application.ports import Heartbeat


def send_heartbeat(heartbeat: Heartbeat) -> None:
    """Use case: emit one outbound liveness ping. Failures must not crash the scheduler."""
    heartbeat.ping()
