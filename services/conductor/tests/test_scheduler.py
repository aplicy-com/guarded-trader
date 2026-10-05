import threading

import structlog

from conductor.adapters.healthchecks import LogHeartbeat
from conductor.infrastructure import scheduler as sch
from conductor.infrastructure.scheduler import LedgerJobs, build_scheduler


def jobs(**overrides: object) -> LedgerJobs:
    base = {
        "ingest": lambda: None,
        "fence": lambda: None,
        "valuation": lambda: None,
        "ingest_interval_seconds": 300,
    }
    return LedgerJobs(**{**base, **overrides})  # type: ignore[arg-type]


def test_ledger_jobs_registered_with_the_right_triggers() -> None:
    s = build_scheduler(LogHeartbeat(), heartbeat_interval_seconds=300, ledger_jobs=jobs())
    ids = {j.id for j in s.get_jobs()}
    assert ids == {
        sch.HEARTBEAT_JOB_ID,
        sch.INGEST_JOB_ID,
        sch.FENCE_JOB_ID,
        sch.FENCE_STARTUP_JOB_ID,
        sch.VALUATION_JOB_ID,
    }
    ingest = s.get_job(sch.INGEST_JOB_ID)
    assert ingest is not None
    assert ingest.trigger.interval.total_seconds() == 300
    fence = s.get_job(sch.FENCE_JOB_ID)
    assert fence is not None
    assert str(fence.trigger.timezone) == "UTC"
    assert (str(fence.trigger.fields[5]), str(fence.trigger.fields[6])) == (
        "0",
        "5",
    )  # hour, minute


def test_no_ledger_jobs_keeps_the_skeleton_behaviour() -> None:
    s = build_scheduler(LogHeartbeat(), heartbeat_interval_seconds=300)
    assert {j.id for j in s.get_jobs()} == {sch.HEARTBEAT_JOB_ID}


def test_a_failing_job_is_logged_not_raised_and_jobs_never_overlap() -> None:
    running = 0
    peak = 0
    guard = threading.Lock()

    def slow() -> None:
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        threading.Event().wait(0.05)
        with guard:
            running -= 1

    def boom() -> None:
        raise RuntimeError("kaboom")

    s = build_scheduler(
        LogHeartbeat(),
        heartbeat_interval_seconds=300,
        ledger_jobs=jobs(ingest=slow, fence=boom, valuation=slow),
    )
    with structlog.testing.capture_logs() as logs:
        threads = [
            threading.Thread(target=s.get_job(i).func)  # type: ignore[union-attr]
            for i in (sch.INGEST_JOB_ID, sch.FENCE_JOB_ID, sch.VALUATION_JOB_ID)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert peak == 1  # serialised by the shared ledger lock
    assert any(e["event"] == "job_failed" and e["job"] == sch.FENCE_JOB_ID for e in logs)


def test_risk_cycle_runs_on_start_and_on_an_interval() -> None:
    s = build_scheduler(
        LogHeartbeat(),
        heartbeat_interval_seconds=300,
        ledger_jobs=jobs(risk=lambda: None, risk_interval_seconds=60),
    )
    ids = {j.id for j in s.get_jobs()}
    assert {sch.RISK_JOB_ID, sch.RISK_STARTUP_JOB_ID} <= ids
    risk = s.get_job(sch.RISK_JOB_ID)
    assert risk is not None
    assert risk.trigger.interval.total_seconds() == 60


def test_backup_job_runs_nightly_at_0315_utc_only_when_configured() -> None:
    off = build_scheduler(LogHeartbeat(), heartbeat_interval_seconds=300, ledger_jobs=jobs())
    assert off.get_job(sch.BACKUP_JOB_ID) is None

    on = build_scheduler(
        LogHeartbeat(),
        heartbeat_interval_seconds=300,
        ledger_jobs=jobs(backup=lambda: None),
    )
    job = on.get_job(sch.BACKUP_JOB_ID)
    assert job is not None
    assert str(job.trigger.timezone) == "UTC"
    assert (str(job.trigger.fields[5]), str(job.trigger.fields[6])) == ("3", "15")  # hour, minute


def test_backup_never_waits_for_the_ledger_lock_and_a_failure_is_only_logged() -> None:
    """A slow upload must not delay risk cycles, and a slow ledger job must not delay a backup."""
    release = threading.Event()
    backup_ran = threading.Event()

    def slow_ingest() -> None:
        release.wait(5)

    def backup() -> None:
        backup_ran.set()
        raise RuntimeError("boom")

    s = build_scheduler(
        LogHeartbeat(),
        heartbeat_interval_seconds=300,
        ledger_jobs=jobs(ingest=slow_ingest, backup=backup),
    )
    ingest, bk = s.get_job(sch.INGEST_JOB_ID), s.get_job(sch.BACKUP_JOB_ID)
    assert ingest is not None and bk is not None
    holder = threading.Thread(target=ingest.func)
    holder.start()  # holds the shared ledger lock
    try:
        runner = threading.Thread(target=bk.func)
        runner.start()
        assert backup_ran.wait(2), "backup was blocked behind the ledger lock"
        runner.join(2)  # and its exception was swallowed (logged), not raised
    finally:
        release.set()
        holder.join()
