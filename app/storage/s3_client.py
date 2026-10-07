import os

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
