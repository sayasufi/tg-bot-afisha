"""MinIO (S3-compatible) object storage for cached event images."""
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from core.config.settings import get_settings

CACHE_CONTROL = "public, max-age=31536000, immutable"


@lru_cache(maxsize=1)
def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.minio_endpoint,
        aws_access_key_id=s.minio_access_key,
        aws_secret_access_key=s.minio_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket() -> None:
    s = get_settings()
    client = _client()
    try:
        client.head_bucket(Bucket=s.minio_bucket)
    except ClientError:
        client.create_bucket(Bucket=s.minio_bucket)


def put_image(key: str, data: bytes, content_type: str = "image/jpeg") -> None:
    s = get_settings()
    _client().put_object(
        Bucket=s.minio_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl=CACHE_CONTROL,
    )


def object_exists(key: str) -> bool:
    s = get_settings()
    try:
        _client().head_object(Bucket=s.minio_bucket, Key=key)
        return True
    except ClientError:
        return False


def get_object(key: str) -> tuple[bytes, str] | None:
    """Return (bytes, content_type) for serving, or None if missing."""
    s = get_settings()
    try:
        resp = _client().get_object(Bucket=s.minio_bucket, Key=key)
    except ClientError:
        return None
    return resp["Body"].read(), resp.get("ContentType", "application/octet-stream")


def public_url(key: str) -> str:
    """Absolute URL the client uses to load an object (falls back to same-origin)."""
    base = get_settings().media_public_base.rstrip("/") or "/v1/media"
    return f"{base}/{key}"
