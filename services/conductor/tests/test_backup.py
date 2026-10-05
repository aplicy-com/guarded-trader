"""3A-5 backups: online SQLite snapshots, write-only upload, audit trail, alerts."""

import gzip
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from conductor.adapters.s3_store import S3ObjectStore
from conductor.adapters.sqlite_backup import SqliteSnapshotter
from conductor.application.backup import (
    BACKUP_COMPLETED,
    BACKUP_FAILED,
    BackupSource,
    SnapshotError,
    backup_key,
    run_backup,
)
from conductor.domain.trading_mode import TradingMode
from conductor.infrastructure.config import Settings
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.infrastructure.observability import region_for, sqlite_path
from conftest import make_settings
from fakes import BrokenNotifier, Clock, RecordingNotifier

NOW = datetime(2026, 10, 4, 3, 15, 7, tzinfo=UTC)


class WriteOnlyStore:
    """Fake bucket with Backblaze write-only-key behaviour: `put` works; anything that reads,
    lists, heads or deletes is AccessDenied. The port exposes only `put`, and this proves it."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_for: set[str] = set()

    def put(self, key: str, path: Path) -> str | None:
        if any(label in key for label in self.fail_for):
            raise ConnectionError("endpoint unreachable")
        self.objects[key] = path.read_bytes()
        return "etag123"

    def __getattr__(self, name: str) -> Any:  # list_objects, head_object, get_object, delete_...
        raise PermissionError(f"AccessDenied: write-only key may not call {name}")


class OnlyPutObjectClient:
    """A boto3-shaped client with ONLY `put_object`: a list/head/get/delete call would raise."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kw: Any) -> dict[str, str]:
        kw["Body"] = kw["Body"].read()
        self.calls.append(kw)
        return {"ETag": '"abc"'}


def make_db(path: Path, rows: int = 50) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def gunzip_to(data: bytes, dest: Path) -> sqlite3.Connection:
    dest.write_bytes(gzip.decompress(data))
    return sqlite3.connect(dest)


def sources(tmp_path: Path) -> list[BackupSource]:
    return [
        BackupSource("conductor", make_db(tmp_path / "ledger.db")),
        BackupSource("freqtrade", make_db(tmp_path / "ft.sqlite", rows=7)),
    ]


# --- key ---------------------------------------------------------------------------------


def test_key_is_dated_sortable_unique_and_per_source() -> None:
    a = backup_key("conductor", NOW, "aaaaaa", TradingMode.DRY_RUN)
    assert a == "backups/dry_run/conductor/conductor-20261004T031507Z-aaaaaa.sqlite.gz"
    later = backup_key(
        "conductor", datetime(2026, 10, 5, 3, 15, tzinfo=UTC), "000000", TradingMode.DRY_RUN
    )
    assert a < later  # lexicographic order == time order, so "latest" is just max(key)
    assert (
        backup_key("conductor", NOW, "bbbbbb", TradingMode.DRY_RUN) != a
    )  # same second, still a new key


def test_naive_looking_offsets_are_normalised_to_utc() -> None:
    from datetime import timedelta, timezone

    at = datetime(2026, 10, 3, 23, 15, 7, tzinfo=timezone(timedelta(hours=-4)))
    assert "20261004T031507Z" in backup_key("x", at, "t", TradingMode.DRY_RUN)


# --- the use case, with a write-only store ---


def test_backup_uploads_each_source_under_a_dated_key_and_audits_it(
    tmp_path: Path, ledger: SqliteLedger
) -> None:
    store = WriteOnlyStore()
    notifier = RecordingNotifier()
    report = run_backup(
        ledger,
        sources(tmp_path),
        SqliteSnapshotter(tmp_path),
        store,
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=notifier,
    )
    assert report.ok
    assert len(store.objects) == 2
    keys = sorted(store.objects)
    assert keys[0].startswith("backups/dry_run/conductor/conductor-20261004T031507Z-")
    assert keys[1].startswith("backups/dry_run/freqtrade/freqtrade-20261004T031507Z-")
    # The uploaded bytes are a real, restorable database.
    conn = gunzip_to(store.objects[keys[1]], tmp_path / "restored.sqlite")
    assert conn.execute("SELECT count(*) FROM t").fetchone() == (7,)
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert notifier.sent == []  # success is silent; the dashboard shows it
    with ledger.transaction(write=False) as repo:
        rows = repo.recent_audit(10, actions=[BACKUP_COMPLETED])
    assert {r.detail["label"] for r in rows} == {"conductor", "freqtrade"}
    for r in rows:
        assert r.actor == "system"
        assert r.detail["integrity_check"] == "ok"
        assert r.detail["key"] in store.objects
        assert len(str(r.detail["sha256"])) == 64
        assert r.detail["etag"] == "etag123"


def test_restored_copy_is_a_single_self_contained_file(
    tmp_path: Path, ledger: SqliteLedger
) -> None:
    store = WriteOnlyStore()
    run_backup(
        ledger,
        sources(tmp_path)[:1],
        SqliteSnapshotter(tmp_path),
        store,
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=None,
    )
    (data,) = store.objects.values()
    assert gzip.decompress(data)[18:20] == b"\x01\x01"  # header: rollback-journal, no WAL needed


def test_two_runs_in_the_same_second_never_overwrite(tmp_path: Path, ledger: SqliteLedger) -> None:
    store = WriteOnlyStore()
    src = sources(tmp_path)[:1]
    for _ in range(2):
        run_backup(
            ledger,
            src,
            SqliteSnapshotter(tmp_path),
            store,
            mode=TradingMode.DRY_RUN,
            now=Clock(NOW),
            notifier=None,
        )
    assert len(store.objects) == 2


def test_upload_failure_alerts_audits_and_does_not_skip_the_other_source(
    tmp_path: Path, ledger: SqliteLedger
) -> None:
    store = WriteOnlyStore()
    store.fail_for = {"conductor"}
    notifier = RecordingNotifier()
    report = run_backup(
        ledger,
        sources(tmp_path),
        SqliteSnapshotter(tmp_path),
        store,
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=notifier,
    )
    assert not report.ok
    assert [o.ok for o in report.outcomes] == [False, True]
    assert list(store.objects) and all("freqtrade" in k for k in store.objects)
    assert len(notifier.sent) == 1
    assert "BACKUP FAILED" in notifier.sent[0]
    assert "conductor" in notifier.sent[0]
    assert "ConnectionError" in notifier.sent[0]
    with ledger.transaction(write=False) as repo:
        failed = repo.recent_audit(10, actions=[BACKUP_FAILED])
        done = repo.recent_audit(10, actions=[BACKUP_COMPLETED])
    assert [r.detail["label"] for r in failed] == ["conductor"]
    assert [r.detail["label"] for r in done] == ["freqtrade"]


def test_missing_source_is_a_failure_not_a_crash(tmp_path: Path, ledger: SqliteLedger) -> None:
    store = WriteOnlyStore()
    notifier = RecordingNotifier()
    report = run_backup(
        ledger,
        [BackupSource("freqtrade", tmp_path / "gone.sqlite")],
        SqliteSnapshotter(tmp_path),
        store,
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=notifier,
    )
    assert not report.ok
    assert store.objects == {}
    assert "not found" in notifier.sent[0]


def test_corrupt_source_is_never_uploaded(tmp_path: Path, ledger: SqliteLedger) -> None:
    bad = tmp_path / "corrupt.sqlite"
    make_db(bad, rows=3000)
    data = bytearray(bad.read_bytes())
    for i in range(4096 * 2, 4096 * 6):  # trash several table pages, keep the header intact
        data[i] = 0xFF
    bad.write_bytes(bytes(data))
    for suffix in ("-wal", "-shm"):
        Path(str(bad) + suffix).unlink(missing_ok=True)
    store = WriteOnlyStore()
    notifier = RecordingNotifier()
    report = run_backup(
        ledger,
        [BackupSource("freqtrade", bad)],
        SqliteSnapshotter(tmp_path),
        store,
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=notifier,
    )
    assert not report.ok
    assert store.objects == {}
    assert "BACKUP FAILED" in notifier.sent[0]


def test_a_broken_notifier_does_not_break_the_backup(tmp_path: Path, ledger: SqliteLedger) -> None:
    store = WriteOnlyStore()
    store.fail_for = {"conductor"}
    n = BrokenNotifier()
    report = run_backup(
        ledger,
        sources(tmp_path),
        SqliteSnapshotter(tmp_path),
        store,
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=n,
    )
    assert n.attempts == 1
    assert [o.ok for o in report.outcomes] == [False, True]


def test_an_audit_write_failure_does_not_hide_the_backup(tmp_path: Path) -> None:
    class DeadLedger:
        def transaction(self, *, write: bool = True) -> Any:
            raise sqlite3.OperationalError("database is locked")

    store = WriteOnlyStore()
    report = run_backup(
        DeadLedger(),
        sources(tmp_path)[:1],
        SqliteSnapshotter(tmp_path),
        store,
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=None,  # type: ignore[arg-type]
    )
    assert report.ok
    assert len(store.objects) == 1


# --- the real snapshotter ---


def test_snapshot_is_consistent_while_the_source_is_being_written(tmp_path: Path) -> None:
    src = make_db(tmp_path / "live.db", rows=2000)
    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        conn = sqlite3.connect(src, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            while not stop.is_set():
                with conn:
                    conn.execute("INSERT INTO t (v) VALUES ('x')")
                    conn.execute("INSERT INTO t (v) VALUES ('y')")
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            conn.close()

    th = threading.Thread(target=writer)
    th.start()
    try:
        for _ in range(5):
            with SqliteSnapshotter(tmp_path).snapshot(src) as snap:
                conn = gunzip_to(snap.path.read_bytes(), tmp_path / "r.sqlite")
                (n,) = conn.execute("SELECT count(*) FROM t").fetchone()
                assert n >= 2000 and n % 2 == 0  # whole transactions only: never half of one
                assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                conn.close()
    finally:
        stop.set()
        th.join()
    assert not errors


def test_snapshot_cleans_up_its_working_files(tmp_path: Path) -> None:
    src = make_db(tmp_path / "a.db")
    work = tmp_path / "work"
    work.mkdir()
    with SqliteSnapshotter(work).snapshot(src) as snap:
        assert snap.path.exists()
        assert snap.gz_bytes == snap.path.stat().st_size
    assert list(work.iterdir()) == []


def test_snapshot_never_modifies_the_source(tmp_path: Path) -> None:
    src = make_db(tmp_path / "a.db")
    before = src.read_bytes()
    with SqliteSnapshotter(tmp_path).snapshot(src):
        pass
    assert src.read_bytes() == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_snapshot_works_on_a_read_only_wal_database_owned_by_a_running_writer(
    tmp_path: Path,
) -> None:
    """The production shape: Freqtrade (WAL, still running, so -wal/-shm exist) and Conductor
    reading it through a read-only mount. Approximated with read-only files and directory."""
    d = tmp_path / "ro"
    d.mkdir()
    src = make_db(d / "tradesv3.dryrun.sqlite", rows=40)
    writer = sqlite3.connect(src)  # stays open, like Freqtrade: keeps -wal and -shm around
    writer.execute("PRAGMA journal_mode=WAL")
    with writer:
        writer.execute("INSERT INTO t (v) VALUES ('uncheckpointed')")  # lives only in the -wal
    assert Path(str(src) + "-wal").exists()
    paths = [d, *d.iterdir()]
    modes = {p: p.stat().st_mode for p in paths}
    for p in paths:
        p.chmod(0o555 if p.is_dir() else 0o444)
    try:
        with SqliteSnapshotter(tmp_path).snapshot(src) as snap:
            conn = gunzip_to(snap.path.read_bytes(), tmp_path / "r.sqlite")
            assert conn.execute("SELECT count(*) FROM t").fetchone() == (41,)  # incl. the -wal row
            conn.close()
    finally:
        for p, m in modes.items():
            p.chmod(m)
        writer.close()


def test_snapshot_error_for_a_non_database_file(tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database" * 500)
    with pytest.raises(SnapshotError), SqliteSnapshotter(tmp_path).snapshot(junk):
        pass


# --- the S3 adapter never asks for more than PutObject ---


def test_s3_store_uses_only_put_object(tmp_path: Path) -> None:
    f = tmp_path / "x.gz"
    f.write_bytes(b"payload")
    client = OnlyPutObjectClient()  # has no list/head/get/delete: using any would raise
    etag = S3ObjectStore(client, "my-bucket").put("backups/a/b.sqlite.gz", f)
    assert etag == "abc"  # quotes stripped
    (call,) = client.calls
    assert call["Bucket"] == "my-bucket"
    assert call["Key"] == "backups/a/b.sqlite.gz"
    assert call["Body"] == b"payload"


def test_full_backup_through_the_s3_adapter_with_a_put_only_client(
    tmp_path: Path, ledger: SqliteLedger
) -> None:
    client = OnlyPutObjectClient()
    report = run_backup(
        ledger,
        sources(tmp_path),
        SqliteSnapshotter(tmp_path),
        S3ObjectStore(client, "b"),
        mode=TradingMode.DRY_RUN,
        now=Clock(NOW),
        notifier=None,
    )
    assert report.ok
    assert [c["Key"].split("/")[2] for c in client.calls] == ["conductor", "freqtrade"]


# --- settings & wiring helpers ---


B2 = {
    "BACKUP_B2_BUCKET": "my-bucket",
    "BACKUP_B2_ENDPOINT": "https://s3.us-west-004.backblazeb2.com",
    "BACKUP_B2_KEY_ID": "keyid-123",
    "BACKUP_B2_APP_KEY": "super-secret-app-key",
}


def test_backup_is_off_when_nothing_is_set(settings: Settings) -> None:
    assert not settings.backup_enabled


def test_blank_values_from_compose_mean_off(db_path: Path) -> None:
    s = make_settings(db_path, **dict.fromkeys(B2, ""), BACKUP_FREQTRADE_DB_PATH="")
    assert not s.backup_enabled
    assert s.backup_freqtrade_db_path is None


def test_all_four_values_enable_backup(db_path: Path) -> None:
    s = make_settings(db_path, **B2)
    assert s.backup_enabled


@pytest.mark.parametrize("drop", sorted(B2))
def test_a_partial_backup_config_is_refused_at_startup(db_path: Path, drop: str) -> None:
    partial = {k: v for k, v in B2.items() if k != drop}
    with pytest.raises(ValueError, match=drop):
        make_settings(db_path, **partial)


def test_backup_secrets_never_appear_in_repr(db_path: Path) -> None:
    text = repr(make_settings(db_path, **B2))
    assert "super-secret-app-key" not in text
    assert "keyid-123" not in text


def test_backup_endpoint_must_be_https(db_path: Path) -> None:
    with pytest.raises(ValueError, match="https"):
        make_settings(db_path, **{**B2, "BACKUP_B2_ENDPOINT": "http://s3.example.com"})


def test_sqlite_path_from_database_url() -> None:
    assert sqlite_path("sqlite:////data/conductor.db") == Path("/data/conductor.db")
    assert sqlite_path("sqlite:///relative.db") == Path("relative.db")


def test_region_comes_from_a_backblaze_endpoint_unless_overridden() -> None:
    assert region_for("s3.us-west-004.backblazeb2.com", None) == "us-west-004"
    assert region_for("s3.eu-central-003.backblazeb2.com", None) == "eu-central-003"
    assert region_for("s3.example.com", None) == "us-east-1"
    assert region_for("s3.us-west-004.backblazeb2.com", "eu-central-003") == "eu-central-003"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_snapshot_of_a_cleanly_stopped_wal_database_on_a_read_only_mount(tmp_path: Path) -> None:
    """Freqtrade stopped: no -wal/-shm, and a read-only mount cannot create them. A plain
    read-only open fails; the snapshotter falls back to immutable (no writer exists)."""
    d = tmp_path / "ro"
    d.mkdir()
    src = make_db(d / "tradesv3.dryrun.sqlite", rows=12)
    assert not Path(f"{src}-wal").exists()
    paths = [d, *d.iterdir()]
    modes = {p: p.stat().st_mode for p in paths}
    for p in paths:
        p.chmod(0o555 if p.is_dir() else 0o444)
    try:
        with pytest.raises(sqlite3.OperationalError):  # the premise: plain read-only is not enough
            c = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True)
            c.execute("SELECT count(*) FROM t").fetchall()
        with SqliteSnapshotter(tmp_path).snapshot(src) as snap:
            conn = gunzip_to(snap.path.read_bytes(), tmp_path / "r.sqlite")
            assert conn.execute("SELECT count(*) FROM t").fetchone() == (12,)
            conn.close()
    finally:
        for p, m in modes.items():
            p.chmod(m)


def test_a_wal_file_that_exists_is_never_bypassed_with_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a -wal exists a writer may be active, so an open failure must surface, not be
    papered over with immutable=1 (which would ignore the WAL and copy stale data)."""
    from conductor.adapters import sqlite_backup

    src = make_db(tmp_path / "a.db")
    Path(f"{src}-wal").write_bytes(b"")  # present (even if empty): treat as a live writer
    calls: list[bool] = []

    def refuse(source: Path, *, immutable: bool) -> sqlite3.Connection:
        calls.append(immutable)
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite_backup, "_connect_source", refuse)
    with (
        pytest.raises(SnapshotError, match="unable to open"),
        SqliteSnapshotter(tmp_path).snapshot(src),
    ):
        pass
    assert calls == [False]


def test_http_and_aws_client_libraries_never_log_requests_even_at_debug() -> None:
    import logging

    from conductor.infrastructure.logging import configure_logging

    configure_logging("DEBUG", json=True)
    for name in ("httpx", "httpcore", "boto3", "botocore", "s3transfer", "urllib3"):
        assert logging.getLogger(name).level == logging.WARNING, name


# --- backups are namespaced by trading mode (ADR-0019) ---------------------------------------


def test_keys_are_namespaced_by_mode_and_never_collide() -> None:
    live = backup_key("conductor", NOW, "aaaaaa", TradingMode.LIVE)
    dry = backup_key("conductor", NOW, "aaaaaa", TradingMode.DRY_RUN)
    assert live == "backups/live/conductor/conductor-20261004T031507Z-aaaaaa.sqlite.gz"
    assert dry == "backups/dry_run/conductor/conductor-20261004T031507Z-aaaaaa.sqlite.gz"
    assert live != dry
    # a mode's prefix is never a prefix of another's, so listing one can't return the other
    assert not live.startswith("backups/dry_run/") and not dry.startswith("backups/live/")


@pytest.mark.parametrize("mode", [TradingMode.LIVE, TradingMode.DRY_RUN])
def test_every_upload_and_audit_record_carries_the_mode(
    tmp_path: Path, ledger: SqliteLedger, mode: TradingMode
) -> None:
    store = WriteOnlyStore()
    report = run_backup(
        ledger,
        sources(tmp_path),
        SqliteSnapshotter(tmp_path),
        store,
        mode=mode,
        now=Clock(NOW),
        notifier=None,
    )
    assert report.ok
    assert len(store.objects) == 2
    assert all(k.startswith(f"backups/{mode.value}/") for k in store.objects)
    other = "live" if mode is TradingMode.DRY_RUN else "dry_run"
    assert not any(k.startswith(f"backups/{other}/") for k in store.objects)
    with ledger.transaction(write=False) as repo:
        rows = repo.recent_audit(10, actions=[BACKUP_COMPLETED])
    assert {r.detail["mode"] for r in rows} == {mode.value}
    assert all(str(r.detail["key"]).startswith(f"backups/{mode.value}/") for r in rows)


def test_the_mode_is_a_required_argument(tmp_path: Path, ledger: SqliteLedger) -> None:
    with pytest.raises(TypeError, match="mode"):
        run_backup(  # type: ignore[call-arg]
            ledger,
            sources(tmp_path),
            SqliteSnapshotter(tmp_path),
            WriteOnlyStore(),
            now=Clock(NOW),
            notifier=None,
        )


def test_the_nightly_job_and_backup_now_use_the_settings_mode(
    tmp_path: Path, db_path: Path
) -> None:
    import re

    src = Path(__file__).parents[1] / "src" / "conductor"
    for name in ("main.py", "cli.py"):
        text = (src / name).read_text()
        call = text[text.index("run_backup(") :]
        assert re.search(r"mode=settings\.trading_mode", call[:400]), name
