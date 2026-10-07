"""The object-store surface the auto-import jobs use, as one injectable object.

Routes (and later the worker) take an ``ObjectStore`` through
``app.deps.get_object_store`` so tests swap in a fake — see ``tests/conftest.py``.
"""

from typing import Protocol

from app.storage import s3_client


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str = ...) -> None: ...
    def get(self, key: str) -> bytes: ...
    def presign(self, key: str, expires_in: int = ...) -> str: ...
    def delete_prefix(self, prefix: str) -> int: ...


class S3ObjectStore:
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        s3_client.put_object(key, data, content_type)

    def get(self, key: str) -> bytes:
        return s3_client.get_image_bytes(key)

    def presign(self, key: str, expires_in: int = 3600) -> str:
        return s3_client.get_presigned_url(key, expires_in)

    def delete_prefix(self, prefix: str) -> int:
        return s3_client.delete_prefix(prefix)
