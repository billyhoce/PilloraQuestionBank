import os
from datetime import datetime

import boto3


def _get_client():
    return boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL"))


def put_image(key: str, data: bytes) -> None:
    _get_client().put_object(
        Bucket=os.environ["S3_BUCKET"],
        Key=key,
        Body=data,
        ContentType="image/webp",
    )


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["S3_BUCKET"], "Key": key},
        ExpiresIn=expires_in,
    )


def copy_only(src_key: str, dst_key: str) -> None:
    """Server-side copy that leaves the source object in place."""
    bucket = os.environ["S3_BUCKET"]
    _get_client().copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": src_key},
        Key=dst_key,
    )


def delete_object(key: str) -> None:
    _get_client().delete_object(Bucket=os.environ["S3_BUCKET"], Key=key)


def get_image_bytes(key: str) -> bytes:
    resp = _get_client().get_object(Bucket=os.environ["S3_BUCKET"], Key=key)
    return resp["Body"].read()


def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    _get_client().put_object(
        Bucket=os.environ["S3_BUCKET"], Key=key, Body=data, ContentType=content_type
    )


def delete_prefix(prefix: str) -> int:
    """Delete every object whose key starts with ``prefix``; returns the count."""
    client = _get_client()
    bucket = os.environ["S3_BUCKET"]
    deleted = 0
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
            deleted += len(keys)
    return deleted


def list_objects(prefix: str) -> list[tuple[str, "datetime"]]:
    """Every ``(key, last_modified)`` under ``prefix`` (one paginated ListObjectsV2 pass);
    ``last_modified`` is timezone-aware UTC."""
    client = _get_client()
    found = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=os.environ["S3_BUCKET"], Prefix=prefix):
        for o in page.get("Contents", []):
            found.append((o["Key"], o["LastModified"]))
    return found


def head_object(key: str) -> tuple[int, str] | None:
    """``(size, content_type)`` of the object, or ``None`` if it does not exist."""
    from botocore.exceptions import ClientError

    try:
        resp = _get_client().head_object(Bucket=os.environ["S3_BUCKET"], Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return resp["ContentLength"], resp.get("ContentType", "")


def presign_post(key: str, content_type: str, min_size: int, max_size: int, expires_in: int) -> dict:
    """A presigned browser POST for ``key``: ``{"url", "fields"}``. Built on the same client (so the
    same ``S3_ENDPOINT_URL``) as :func:`get_presigned_url`; the signed policy pins the key, the
    ``Content-Type`` and the ``content-length-range``."""
    return _get_client().generate_presigned_post(
        Bucket=os.environ["S3_BUCKET"],
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", min_size, max_size],
        ],
        ExpiresIn=expires_in,
    )
