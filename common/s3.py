# common/s3.py
import boto3
from config import S3_BUCKET_NAME, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

def get_bucket_name() -> str:
    bucket = (S3_BUCKET_NAME or "").strip()
    if not bucket:
        raise RuntimeError("S3 bucket name is missing")
    return bucket

def get_s3_client():
    region = (AWS_REGION or "").strip()
    if not region:
        raise RuntimeError("AWS region is missing")

    if not (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY):
        raise RuntimeError("Missing AWS credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)")

    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )