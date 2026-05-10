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


def copy_object(src_key: str, dst_key: str) -> None:
    bucket = os.environ["S3_BUCKET"]
    client = _get_client()
    client.copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": src_key},
        Key=dst_key,
    )
    client.delete_object(Bucket=bucket, Key=src_key)


def delete_object(key: str) -> None:
    _get_client().delete_object(Bucket=os.environ["S3_BUCKET"], Key=key)


def get_image_bytes(key: str) -> bytes:
    resp = _get_client().get_object(Bucket=os.environ["S3_BUCKET"], Key=key)
    return resp["Body"].read()
