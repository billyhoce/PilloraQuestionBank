"""The object-store surface the auto-import jobs use, as one injectable object.

Routes (and later the worker) take an ``ObjectStore`` through
``app.deps.get_object_store`` so tests swap in a fake — see ``tests/conftest.py``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.storage import s3_client


@dataclass(frozen=True)
class StoredObject:
    key: str
    last_modified: datetime  # timezone-aware


@dataclass(frozen=True)
class ObjectHead:
    size: int
    content_type: str


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str = ...) -> None: ...
    def get(self, key: str) -> bytes: ...
    def presign(self, key: str, expires_in: int = ...) -> str: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def delete(self, key: str) -> None: ...
    def list_objects(self, prefix: str) -> list[StoredObject]: ...
    def head(self, key: str) -> ObjectHead | None: ...
    def presign_post(
        self, key: str, content_type: str, min_size: int, max_size: int, expires_in: int
    ) -> dict: ...


class S3ObjectStore:
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        s3_client.put_object(key, data, content_type)

    def get(self, key: str) -> bytes:
        return s3_client.get_image_bytes(key)

    def presign(self, key: str, expires_in: int = 3600) -> str:
        return s3_client.get_presigned_url(key, expires_in)

    def delete_prefix(self, prefix: str) -> int:
        return s3_client.delete_prefix(prefix)

    def delete(self, key: str) -> None:
        s3_client.delete_object(key)

    def list_objects(self, prefix: str) -> list[StoredObject]:
        return [StoredObject(k, m) for k, m in s3_client.list_objects(prefix)]

    def head(self, key: str) -> ObjectHead | None:
        found = s3_client.head_object(key)
        return None if found is None else ObjectHead(*found)

    def presign_post(
        self, key: str, content_type: str, min_size: int, max_size: int, expires_in: int
    ) -> dict:
        return s3_client.presign_post(key, content_type, min_size, max_size, expires_in)
