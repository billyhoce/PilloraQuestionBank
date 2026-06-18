"""Tests for the S3 storage helper module (moto-mocked)."""
import pytest
import boto3
from botocore.exceptions import ClientError

from app.storage.s3_client import (
    copy_only,
    delete_object,
    get_presigned_url,
    put_image,
)

_BUCKET = "test-bucket"
_KEY = "papers/1/q1/question_0.webp"
_DATA = b"fake-webp-image-bytes"


def test_put_image_stores_object(mock_s3):
    put_image(_KEY, _DATA)
    resp = mock_s3.head_object(Bucket=_BUCKET, Key=_KEY)
    assert resp["ResponseMetadata"]["HTTPStatusCode"] == 200


def test_put_image_sets_content_type_webp(mock_s3):
    put_image(_KEY, _DATA)
    resp = mock_s3.head_object(Bucket=_BUCKET, Key=_KEY)
    assert resp["ContentType"] == "image/webp"


def test_get_presigned_url_returns_string(mock_s3):
    put_image(_KEY, _DATA)
    url = get_presigned_url(_KEY, expires_in=3600)
    assert isinstance(url, str)
    assert len(url) > 0


def test_get_presigned_url_contains_expiry_param(mock_s3):
    put_image(_KEY, _DATA)
    url = get_presigned_url(_KEY, expires_in=3600)
    # moto generates standard SigV4 presigned URLs
    assert "X-Amz-Expires" in url or "Expires" in url


def test_copy_only_copies_leaving_source(mock_s3):
    src = "tmp/upload-123/page_0.webp"
    dst = "papers/5/q1/question_0.webp"
    mock_s3.put_object(Bucket=_BUCKET, Key=src, Body=_DATA)

    copy_only(src, dst)

    # Destination exists
    mock_s3.head_object(Bucket=_BUCKET, Key=dst)
    # Source is left in place (copy, not move)
    mock_s3.head_object(Bucket=_BUCKET, Key=src)


def test_delete_object_removes_key(mock_s3):
    mock_s3.put_object(Bucket=_BUCKET, Key=_KEY, Body=_DATA)
    delete_object(_KEY)
    with pytest.raises(ClientError):
        mock_s3.head_object(Bucket=_BUCKET, Key=_KEY)


def test_put_image_wrong_bucket_raises(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "nonexistent-bucket")
    with pytest.raises(Exception):
        put_image(_KEY, _DATA)


def test_put_image_large_bytes_succeeds(mock_s3):
    large_data = b"x" * (1024 * 1024)  # 1 MB
    put_image(_KEY, large_data)
    resp = mock_s3.head_object(Bucket=_BUCKET, Key=_KEY)
    assert resp["ContentLength"] == 1024 * 1024
