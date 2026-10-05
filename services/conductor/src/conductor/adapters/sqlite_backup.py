"""Consistent SQLite snapshots via the online backup API, never a file copy."""

import gzip
import hashlib
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from conductor.application.backup import Snapshot, SnapshotError

BUSY_TIMEOUT_SECONDS = 30.0
CHUNK = 1024 * 1024


def _connect_source(source: Path, *, immutable: bool) -> sqlite3.Connection:
    uri = f"{source.resolve().as_uri()}?mode=ro" + ("&immutable=1" if immutable else "")
    return sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS)


def _open_source(source: Path) -> sqlite3.Connection:
    conn: sqlite3.Connection | None = None
    try:
        conn = _connect_source(source, immutable=False)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchall()  # really opens the file
        return conn
    except sqlite3.OperationalError:
        if conn is not None:
            conn.close()
        if Path(f"{source}-wal").exists():
            raise
    return _connect_source(source, immutable=True)


def _online_backup(source: Path, dest: Path) -> None:
    """Copy ``source`` into ``dest`` with SQLite's backup API.

    The source is opened ``mode=ro``: it never creates or modifies a file, so it works on a
    read-only mount. A WAL-mode source on a read-only mount needs its ``-wal`` and ``-shm``
    files visible (the whole directory mounted) and its owner running.

    One case cannot work that way: the owner has stopped cleanly, so SQLite has removed
    ``-wal``/``-shm``, and a read-only mount lets us create neither. With no ``-wal`` there is
    no writer and nothing unmerged, so a retry with ``immutable=1`` is safe; if the owner
    restarts mid-copy the integrity check on the copy is the backstop.
    """
    with closing(_open_source(source)) as src, closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)
        # One self-contained file: no -wal/-shm needed to open the restored copy.
        dst.execute("PRAGMA journal_mode=DELETE").fetchall()


def _integrity_check(path: Path) -> None:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        rows = [str(r[0]) for r in conn.execute("PRAGMA integrity_check")]
    if rows != ["ok"]:
        raise SnapshotError("integrity_check failed on the copy: " + "; ".join(rows[:5]))


def _gzip(src: Path, dest: Path) -> tuple[int, str]:
    """Gzip ``src`` to ``dest`` (no timestamp, so identical data gives identical bytes).
    Returns (gz size, sha256 of the gz file)."""
    with (
        src.open("rb") as fin,
        dest.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz,
    ):
        shutil.copyfileobj(fin, gz, CHUNK)
    digest = hashlib.sha256()
    with dest.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return dest.stat().st_size, digest.hexdigest()


class SqliteSnapshotter:
    """`DatabaseSnapshotter`. Working files go in a private temp dir, removed on exit."""

    def __init__(self, tmp_root: Path | None = None) -> None:
        self._tmp_root = tmp_root

    @contextmanager
    def snapshot(self, source: Path) -> Iterator[Snapshot]:
        if not source.is_file():
            raise SnapshotError(f"source database not found: {source}")
        with tempfile.TemporaryDirectory(prefix="backup-", dir=self._tmp_root) as tmp:
            copy = Path(tmp) / "copy.sqlite"
            try:
                _online_backup(source, copy)
            except sqlite3.Error as exc:
                raise SnapshotError(f"online backup failed: {exc}") from exc
            try:
                _integrity_check(copy)
            except sqlite3.Error as exc:
                raise SnapshotError(f"integrity_check could not run on the copy: {exc}") from exc
            raw = copy.stat().st_size
            gz_path = Path(tmp) / "copy.sqlite.gz"
            gz_bytes, sha = _gzip(copy, gz_path)
            copy.unlink()
            yield Snapshot(path=gz_path, raw_bytes=raw, gz_bytes=gz_bytes, sha256=sha)
