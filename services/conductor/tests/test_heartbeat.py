"""3A-5 heartbeat: when it pings OK vs /fail vs nothing, and how the ping is delivered."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from conductor.adapters.healthchecks import HealthchecksHeartbeat, HeartbeatDeliveryError
from conductor.application.health import HealthReport
from conductor.application.heartbeat import (
    RISK_CYCLE_MAX_AGE,
    HeartbeatDecision,
    HeartbeatLog,
    RiskCycleMonitor,
    decide_heartbeat,
    send_heartbeat,
)
from conductor.application.ingest import FreqtradeInstance
from conductor.infrastructure import scheduler as sch
from conductor.infrastructure.config import Settings
from conductor.main import create_app
from conftest import make_settings
from fakes import Clock, FakeFreqtrade, FakeFx

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
GOOD = HealthReport(ok=True, db_ok=True, db_journal_mode="wal", scheduler_running=True)
URL = "https://hc-ping.com/11111111-2222-3333-4444-555555555555"


def decide(
    report: HealthReport = GOOD,
    last: datetime | None = NOW - timedelta(seconds=60),
    **kw: object,
) -> HeartbeatDecision:
    return decide_heartbeat(report, last, NOW, risk_cycle_required=True, **kw)  # type: ignore[arg-type]


# --- decision logic ---------------------------------------------------------------


def test_healthy_when_db_scheduler_and_recent_risk_cycle_are_ok() -> None:
    assert decide() == HeartbeatDecision(True)


def test_risk_cycle_age_boundary_is_three_minutes() -> None:
    assert timedelta(minutes=3) == RISK_CYCLE_MAX_AGE
    assert decide(last=NOW - timedelta(minutes=3)).healthy
    late = decide(last=NOW - timedelta(minutes=3, seconds=1))
    assert not late.healthy
    assert "risk cycle" in late.reason


def test_unhealthy_when_no_risk_cycle_has_succeeded_yet() -> None:
    d = decide(last=None)
    assert not d.healthy
    assert "no successful risk cycle" in d.reason


def test_unhealthy_when_database_not_ok() -> None:
    bad = HealthReport(ok=False, db_ok=False, db_journal_mode="error", scheduler_running=True)
    d = decide(bad)
    assert not d.healthy
    assert "database unhealthy" in d.reason
    assert "journal_mode=error" in d.reason


def test_unhealthy_when_scheduler_not_running() -> None:
    d = decide(HealthReport(ok=False, db_ok=True, db_journal_mode="wal", scheduler_running=False))
    assert not d.healthy
    assert "scheduler not running" in d.reason


def test_all_failing_conditions_are_reported_and_reason_is_short() -> None:
    bad = HealthReport(ok=False, db_ok=False, db_journal_mode="error", scheduler_running=False)
    d = decide(bad, last=None)
    assert not d.healthy
    for part in ("database unhealthy", "scheduler not running", "no successful risk cycle"):
        assert part in d.reason
    assert len(d.reason) <= 200


def test_risk_cycle_not_required_when_scheduler_is_disabled() -> None:
    off = HealthReport(ok=True, db_ok=True, db_journal_mode="wal", scheduler_running=False)
    assert decide_heartbeat(off, None, NOW, risk_cycle_required=False).healthy
    broken = HealthReport(ok=False, db_ok=False, db_journal_mode="error", scheduler_running=False)
    assert not decide_heartbeat(broken, None, NOW, risk_cycle_required=False).healthy


def test_monitor_remembers_only_the_last_success() -> None:
    m = RiskCycleMonitor()
    assert m.last_success is None
    m.record_success(NOW)
    assert m.last_success == NOW


# --- send_heartbeat ------------------------------------------------------------------


class RecordingHeartbeat:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_with = fail_with

    def ok(self) -> None:
        self.calls.append(("ok", ""))
        if self.fail_with:
            raise self.fail_with

    def fail(self, reason: str) -> None:
        self.calls.append(("fail", reason))
        if self.fail_with:
            raise self.fail_with


def test_healthy_decision_pings_ok_and_is_logged() -> None:
    hb, log = RecordingHeartbeat(), HeartbeatLog()
    send_heartbeat(hb, lambda: HeartbeatDecision(True), now=lambda: NOW, history=log)
    assert hb.calls == [("ok", "")]
    assert log.snapshot() == (NOW, NOW, "ok", "")


def test_unhealthy_decision_pings_fail_with_the_reason() -> None:
    hb, log = RecordingHeartbeat(), HeartbeatLog()
    send_heartbeat(hb, lambda: HeartbeatDecision(False, "db down"), now=lambda: NOW, history=log)
    assert hb.calls == [("fail", "db down")]
    attempt, last_ok, outcome, reason = log.snapshot()
    assert (attempt, last_ok, outcome, reason) == (NOW, None, "fail_sent", "db down")


def test_delivery_failure_is_recorded_and_raised_for_the_scheduler_to_log() -> None:
    hb, log = RecordingHeartbeat(fail_with=ConnectionError("x")), HeartbeatLog()
    with pytest.raises(ConnectionError):
        send_heartbeat(hb, lambda: HeartbeatDecision(True), now=lambda: NOW, history=log)
    assert log.snapshot()[2] == "delivery_failed"


# --- healthchecks.io adapter ------------------------------------------------------------


def hc(handler: httpx.MockTransport) -> HealthchecksHeartbeat:
    return HealthchecksHeartbeat(URL + "/", httpx.Client(transport=handler))


def test_ok_pings_the_url_and_fail_pings_slash_fail_with_the_reason() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="OK")

    beat = hc(httpx.MockTransport(handler))
    beat.ok()
    beat.fail("scheduler not running")
    assert [str(r.url) for r in seen] == [URL, URL + "/fail"]
    assert seen[1].content == b"scheduler not running"


def test_delivery_retries_once_then_raises_without_leaking_the_url() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(HeartbeatDeliveryError) as err:
        hc(httpx.MockTransport(handler)).ok()
    assert calls == 2
    assert "11111111" not in str(err.value)
    assert "ConnectError" in str(err.value)


def test_http_error_status_is_a_failure_and_does_not_leak_the_url() -> None:
    beat = hc(httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(HeartbeatDeliveryError) as err:
        beat.ok()
    assert "404" in str(err.value)
    assert "11111111" not in str(err.value)


def test_a_retry_that_succeeds_is_fine() -> None:
    responses = iter([httpx.Response(500), httpx.Response(200)])
    hc(httpx.MockTransport(lambda r: next(responses))).ok()


# --- settings -------------------------------------------------------------------------------


def test_ping_url_is_read_from_healthcheck_ping_url_and_never_printed(
    db_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEALTHCHECK_PING_URL", URL)
    s = make_settings(db_path)  # type: ignore[arg-type]
    assert s.healthchecks_ping_url is not None
    assert s.healthchecks_ping_url.get_secret_value() == URL
    assert "11111111" not in repr(s)


def test_blank_ping_url_means_no_external_heartbeat(
    db_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEALTHCHECK_PING_URL", "")
    assert make_settings(db_path).healthchecks_ping_url is None  # type: ignore[arg-type]


def test_ping_url_must_be_http(db_path: object) -> None:
    with pytest.raises(ValueError, match="http"):
        make_settings(db_path, HEALTHCHECK_PING_URL="ftp://nope")  # type: ignore[arg-type]


# --- wired into the app ------------------------------------------------------------------------


@contextmanager
def wired(  # type: ignore[no-untyped-def]
    settings: Settings, hb: RecordingHeartbeat, clock: Clock, *, started: bool = True
):
    """The real app wiring with the scheduler started but paused (running, no job fires on
    its own); jobs are invoked by hand."""
    app = create_app(
        settings.model_copy(update={"scheduler_enabled": True}),
        instances=[FreqtradeInstance("primary", FakeFreqtrade(), FakeFreqtrade())],
        fx=FakeFx(),
        heartbeat=hb,
        clock=clock,
    )
    sched = app.state.scheduler
    if started:
        sched.start(paused=True)

    def job(job_id: str) -> None:
        j = sched.get_job(job_id)
        assert j is not None
        j.func()

    try:
        yield job
    finally:
        if sched.running:
            sched.shutdown(wait=False)


def test_heartbeat_tracks_the_risk_cycle_end_to_end(settings: Settings, clock: Clock) -> None:
    hb = RecordingHeartbeat()
    with wired(settings, hb, clock) as job:
        job(sch.HEARTBEAT_JOB_ID)
        assert hb.calls[-1][0] == "fail"
        assert "no successful risk cycle" in hb.calls[-1][1]

        job(sch.RISK_JOB_ID)
        job(sch.HEARTBEAT_JOB_ID)
        assert hb.calls[-1] == ("ok", "")

        clock.at += timedelta(minutes=4)  # the risk job stops running
        job(sch.HEARTBEAT_JOB_ID)
        assert hb.calls[-1][0] == "fail"
        assert "risk cycle" in hb.calls[-1][1]


def test_a_risk_cycle_that_raises_is_not_a_success(
    settings: Settings, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("risk cycle exploded")

    monkeypatch.setattr("conductor.main.run_risk_cycle", boom)
    hb = RecordingHeartbeat()
    with wired(settings, hb, clock) as job:
        job(sch.RISK_JOB_ID)  # the scheduler wrapper logs the failure, never raises
        job(sch.HEARTBEAT_JOB_ID)
        assert hb.calls[-1][0] == "fail"
        assert "no successful risk cycle" in hb.calls[-1][1]


def test_scheduler_not_running_pings_fail_not_ok(settings: Settings, clock: Clock) -> None:
    hb = RecordingHeartbeat()
    with wired(settings, hb, clock, started=False) as job:
        job(sch.RISK_JOB_ID)
        job(sch.HEARTBEAT_JOB_ID)
        assert hb.calls[-1][0] == "fail"
        assert "scheduler not running" in hb.calls[-1][1]
