"""Where snapshot tarballs live: Cloudflare R2, or the dev MinIO.

R2 speaks S3, so this is the storage module's boto3 pattern pointed at a
second bucket. It is its own client rather than a mode of services/storage
because attachments and snapshots have different owners, lifetimes and
buckets, and a switch of one must never move the other.

Keys are `{R2_PREFIX}projects/{project_id}/snapshots/{seq}.tgz`.
"""
import asyncio
import logging

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

log = logging.getLogger("vivid.builder.blob")

_client = None


class BlobError(Exception):
    """The store could not be reached or refused the operation."""


def configured() -> bool:
    return bool(_endpoint() and _bucket())


def _endpoint() -> str:
    if settings.R2_ENDPOINT:
        return settings.R2_ENDPOINT
    if settings.R2_ACCOUNT_ID:
        return f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return settings.S3_ENDPOINT_URL


def _bucket() -> str:
    return settings.R2_BUCKET or settings.S3_BUCKET


def _using_r2() -> bool:
    return bool(settings.R2_ENDPOINT or settings.R2_ACCOUNT_ID)


def client():
    global _client
    if _client is None:
        r2 = _using_r2()
        _client = boto3.client(
            "s3",
            endpoint_url=_endpoint(),
            aws_access_key_id=settings.R2_ACCESS_KEY_ID if r2 else settings.S3_ACCESS_KEY,
            aws_secret_access_key=(settings.R2_SECRET_ACCESS_KEY if r2
                                   else settings.S3_SECRET_KEY),
            # R2 wants "auto"; MinIO ignores it.
            region_name="auto" if r2 else settings.S3_REGION,
            config=Config(signature_version="s3v4"))
    return _client


def reset() -> None:
    """Drop the cached client (tests swap settings)."""
    global _client
    _client = None


def snapshot_key(project_id: str, seq: int) -> str:
    return f"{settings.R2_PREFIX}projects/{project_id}/snapshots/{seq}.tgz"


def publish_key(project_id: str, publish_id: str) -> str:
    return f"{settings.R2_PREFIX}projects/{project_id}/publishes/{publish_id}.tgz"


def asset_key(project_id: str, asset_id: str, name: str) -> str:
    return f"{settings.R2_PREFIX}projects/{project_id}/assets/{asset_id}-{name}"


def presigned_url(key: str, expires_in: int = 3600) -> str:
    """A time-limited GET URL: for showing an asset in a client, and for
    handing an image to the plan model."""
    return client().generate_presigned_url(
        "get_object", Params={"Bucket": _bucket(), "Key": key}, ExpiresIn=expires_in)


async def put(key: str, data: bytes, content_type: str = "application/gzip") -> None:
    try:
        await asyncio.to_thread(client().put_object, Bucket=_bucket(), Key=key,
                                Body=data, ContentType=content_type)
    except (BotoCoreError, ClientError) as e:
        raise BlobError(f"upload of {key} failed: {e}") from e


async def get(key: str) -> bytes:
    def _get() -> bytes:
        return client().get_object(Bucket=_bucket(), Key=key)["Body"].read()
    try:
        return await asyncio.to_thread(_get)
    except (BotoCoreError, ClientError) as e:
        raise BlobError(f"download of {key} failed: {e}") from e


async def delete_prefix(prefix: str) -> int:
    """Remove every object under a prefix (a deleted project). Returns the
    count. Best effort: a failure is logged, the rows are gone regardless."""
    def _delete() -> int:
        bucket = _bucket()
        paginator = client().get_paginator("list_objects_v2")
        removed = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                client().delete_objects(Bucket=bucket, Delete={"Objects": keys})
                removed += len(keys)
        return removed
    try:
        return await asyncio.to_thread(_delete)
    except (BotoCoreError, ClientError) as e:
        log.warning("could not delete objects under %s: %s", prefix, e)
        return 0
