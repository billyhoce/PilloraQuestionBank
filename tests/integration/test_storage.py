"""Integration tests — real AWS S3 calls."""
import os
import uuid

import boto3
import pytest
from botocore.exceptions import ClientError

from app.storage.s3_client import _get_client, copy_only, delete_object, get_image_bytes, put_image


@pytest.fixture
def s3_prefix():
    """Unique key prefix; all objects cleaned up on teardown."""
    from app.storage.s3_client import _get_client
    prefix = f"integration-test/{uuid.uuid4().hex}"
    yield prefix
    bucket = os.environ["S3_BUCKET"]
    client = _get_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=obj["Key"])


def test_put_and_get(s3_prefix):
    """put_image stores bytes; get_image_bytes retrieves them intact."""
    key = f"{s3_prefix}/test.webp"
    data = b"fake-webp-bytes"

    put_image(key, data)
    assert get_image_bytes(key) == data


def test_copy_only_copies_key(s3_prefix):
    """copy_only copies src to dst and leaves src in place."""
    src = f"{s3_prefix}/src.webp"
    dst = f"{s3_prefix}/dst.webp"
    bucket = os.environ["S3_BUCKET"]

    put_image(src, b"data")
    copy_only(src, dst)

    client = _get_client()
    client.head_object(Bucket=bucket, Key=dst)
    client.head_object(Bucket=bucket, Key=src)


def test_delete_object(s3_prefix):
    """delete_object removes the key."""
    key = f"{s3_prefix}/to-delete.webp"
    bucket = os.environ["S3_BUCKET"]

    put_image(key, b"data")
    delete_object(key)

    with pytest.raises(ClientError):
        _get_client().head_object(Bucket=bucket, Key=key)
