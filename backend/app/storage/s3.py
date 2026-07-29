import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
    return _s3_client


def ensure_bucket() -> None:
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def upload_file(local_path: str, key: str) -> str:
    ensure_bucket()
    get_s3_client().upload_file(local_path, settings.s3_bucket, key)
    return key


def download_file(key: str, local_path: str) -> None:
    get_s3_client().download_file(settings.s3_bucket, key, local_path)


def delete_prefix(prefix: str) -> None:
    """Delete every object under a key prefix. Used to purge a job's temporary
    media (video/audio/frames) once the pipeline no longer needs it."""
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": keys})
