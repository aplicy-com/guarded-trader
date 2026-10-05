"""S3-compatible object store (Backblaze B2) with a deliberately single operation: PutObject.

The backup credentials are write-only, so this adapter must never issue ListObjects,
HeadObject, GetObject or DeleteObject: those would fail with AccessDenied. The client is
duck-typed on purpose so the tests can hand it a fake that has ONLY ``put_object``.
"""

from pathlib import Path
from typing import Any


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, path: Path) -> str | None:
        with path.open("rb") as body:
            response = self._client.put_object(
                Bucket=self._bucket, Key=key, Body=body, ContentType="application/gzip"
            )
        etag = response.get("ETag") if isinstance(response, dict) else None
        return str(etag).strip('"') if etag else None
