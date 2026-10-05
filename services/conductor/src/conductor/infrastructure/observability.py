"""Builds the 3A-5 observability adapters from settings: heartbeat and backup."""

import re
import tempfile
from collections.abc import Callable
from pathlib import Path

import boto3
import httpx
from botocore.config import Config

from conductor.adapters.healthchecks import HealthchecksHeartbeat, LogHeartbeat
from conductor.adapters.s3_store import S3ObjectStore
from conductor.adapters.sqlite_backup import SqliteSnapshotter
from conductor.application.backup import BackupSource, DatabaseSnapshotter, ObjectStore
from conductor.application.ports import Heartbeat
from conductor.infrastructure.config import Settings

_B2_REGION = re.compile(r"^s3\.([a-z0-9-]+)\.backblazeb2\.com$")


def build_heartbeat(settings: Settings) -> tuple[Heartbeat, list[Callable[[], None]]]:
    """healthchecks.io when HEALTHCHECK_PING_URL is set, else log-only (no network)."""
    if settings.healthchecks_ping_url is None:
        return LogHeartbeat(), []
    client = httpx.Client(follow_redirects=False)
    return HealthchecksHeartbeat(settings.healthchecks_ping_url.get_secret_value(), client), [
        client.close
    ]


def sqlite_path(database_url: str) -> Path:
    """The file behind a ``sqlite:///...`` URL (``sqlite:////data/x.db`` is ``/data/x.db``)."""
    return Path(database_url.removeprefix("sqlite:///"))


def region_for(endpoint_host: str, override: str | None) -> str:
    """SigV4 needs the right region. Backblaze encodes it in the endpoint host."""
    if override:
        return override
    match = _B2_REGION.match(endpoint_host)
    return match.group(1) if match else "us-east-1"


def build_object_store(settings: Settings) -> ObjectStore:
    assert settings.backup_b2_endpoint is not None  # noqa: S101  (guarded by backup_enabled)
    assert settings.backup_b2_bucket is not None  # noqa: S101
    assert settings.backup_b2_key_id is not None  # noqa: S101
    assert settings.backup_b2_app_key is not None  # noqa: S101
    client = boto3.client(
        "s3",
        endpoint_url=str(settings.backup_b2_endpoint).rstrip("/"),
        aws_access_key_id=settings.backup_b2_key_id.get_secret_value(),
        aws_secret_access_key=settings.backup_b2_app_key.get_secret_value(),
        region_name=region_for(settings.backup_b2_endpoint.host or "", settings.backup_b2_region),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=120,
            # B2's S3 API does not take boto3's newer default CRC32 trailer checksums.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    return S3ObjectStore(client, settings.backup_b2_bucket)


def build_backup_sources(settings: Settings) -> list[BackupSource]:
    sources = [BackupSource("conductor", sqlite_path(settings.database_url))]
    if settings.backup_freqtrade_db_path is not None:
        sources.append(BackupSource("freqtrade", settings.backup_freqtrade_db_path))
    return sources


def build_snapshotter() -> DatabaseSnapshotter:
    return SqliteSnapshotter(Path(tempfile.gettempdir()))
