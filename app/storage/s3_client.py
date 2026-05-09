"""S3 storage helpers — stub for TDD. Implement to make tests pass."""


def put_image(key: str, data: bytes) -> None:
    raise NotImplementedError


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    raise NotImplementedError


def copy_object(src_key: str, dst_key: str) -> None:
    raise NotImplementedError


def delete_object(key: str) -> None:
    raise NotImplementedError


def get_image_bytes(key: str) -> bytes:
    raise NotImplementedError
