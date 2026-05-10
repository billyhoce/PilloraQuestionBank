import os

import boto3


def put_image(key: str, data: bytes) -> None:
    raise NotImplementedError


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    s3 = boto3.client("s3")
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["S3_BUCKET"], "Key": key},
        ExpiresIn=expires_in,
    )


def copy_object(src_key: str, dst_key: str) -> None:
    raise NotImplementedError


def delete_object(key: str) -> None:
    raise NotImplementedError


def get_image_bytes(key: str) -> bytes:
    raise NotImplementedError
