"""Nightly backups (3A-5): consistent SQLite copies, verified, gzipped, uploaded.

For each source database: take an online backup (never a file copy), run
``PRAGMA integrity_check`` on the COPY, gzip it, and upload under a fresh dated key. Only
a database that passed its integrity check is ever uploaded. The credentials are
write-only, so the object store port has exactly one operation, ``put``: there is no way
to list, head, read or delete, and therefore nothing here that depends on doing so. Proof
that an upload is restorable comes from the restore drill, not from reading it back.

Every outcome is recorded in the ledger audit log; any failure raises one Telegram alert.
"""

import secrets
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import structlog

from conductor.application.ledger_ports import Ledger
from conductor.application.notify import safe_send
from conductor.application.ports import Notifier

log = structlog.get_logger()
Clock = Callable[[], datetime]

KEY_PREFIX = "backups"
BACKUP_COMPLETED = "backup_completed"
BACKUP_FAILED = "backup_failed"
BACKUP_ACTOR = "system"
MAX_DETAIL_CHARS = 300


class SnapshotError(RuntimeError):
    """The source could not be copied, or the copy failed its integrity check."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    path: Path  # the gzipped, integrity-checked copy
    raw_bytes: int
    gz_bytes: int
    sha256: str  # of the gzipped file


class DatabaseSnapshotter(Protocol):
    def snapshot(self, source: Path) -> AbstractContextManager[Snapshot]:
        """Online-backup ``source``, integrity-check the copy, gzip it. Raises SnapshotError.
        The files live until the context exits."""
        ...


class ObjectStore(Protocol):
    """Write-only on purpose. Do not add list/head/get/delete."""

    def put(self, key: str, path: Path) -> str | None:
        """Upload ``path`` under ``key``; returns the store's ETag if it gave one."""
        ...


@dataclass(frozen=True, slots=True)
class BackupSource:
    label: str  # "conductor" | "freqtrade": part of the key and of the audit record
    path: Path


@dataclass(frozen=True, slots=True)
class BackupOutcome:
    label: str
    ok: bool
    key: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class BackupReport:
    outcomes: tuple[BackupOutcome, ...]

    @property
    def ok(self) -> bool:
        return all(o.ok for o in self.outcomes)


def backup_key(label: str, at: datetime, token: str) -> str:
    """Dated, unique, sortable key: later backups sort later, and a repeat never reuses a key."""
    stamp = at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{KEY_PREFIX}/{label}/{label}-{stamp}-{token}.sqlite.gz"


def _audit(ledger: Ledger, at: datetime, action: str, detail: dict[str, object]) -> None:
    """Best effort: a ledger write problem must not hide the backup result."""
    try:
        with ledger.transaction() as repo:
            repo.add_audit(at, BACKUP_ACTOR, action, detail)
    except Exception:
        log.exception("backup_audit_failed", action=action)


def _backup_one(
    source: BackupSource,
    snapshotter: DatabaseSnapshotter,
    store: ObjectStore,
    now: Clock,
    token: Callable[[], str],
) -> tuple[str, Snapshot, str | None]:
    with snapshotter.snapshot(source.path) as snap:
        key = backup_key(source.label, now(), token())
        etag = store.put(key, snap.path)
        return key, snap, etag


def run_backup(
    ledger: Ledger,
    sources: Sequence[BackupSource],
    snapshotter: DatabaseSnapshotter,
    store: ObjectStore,
    *,
    now: Clock,
    notifier: Notifier | None,
    token: Callable[[], str] = lambda: secrets.token_hex(3),
) -> BackupReport:
    """Back up every source independently (one failing never skips the other)."""
    outcomes: list[BackupOutcome] = []
    for source in sources:
        try:
            key, snap, etag = _backup_one(source, snapshotter, store, now, token)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:MAX_DETAIL_CHARS]
            log.error("backup_failed", label=source.label, error=detail)
            _audit(ledger, now(), BACKUP_FAILED, {"label": source.label, "error": detail})
            outcomes.append(BackupOutcome(source.label, False, None, detail))
            continue
        _audit(
            ledger,
            now(),
            BACKUP_COMPLETED,
            {
                "label": source.label,
                "key": key,
                "raw_bytes": snap.raw_bytes,
                "gz_bytes": snap.gz_bytes,
                "sha256": snap.sha256,
                "etag": etag,
                "integrity_check": "ok",
            },
        )
        log.info("backup_completed", label=source.label, key=key, gz_bytes=snap.gz_bytes)
        outcomes.append(BackupOutcome(source.label, True, key, f"{snap.gz_bytes} bytes gzipped"))
    report = BackupReport(tuple(outcomes))
    failed = [o for o in outcomes if not o.ok]
    if failed:
        lines = "\n".join(f"- {o.label}: {o.detail}" for o in failed)
        safe_send(notifier, f"BACKUP FAILED ({len(failed)}/{len(outcomes)} sources):\n{lines}")
    return report
