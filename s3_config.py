# Nickodemus made this file and code
import os
import boto3  # type: ignore[import-not-found]

aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_REGION", "us-east-1")
bucket_name = os.getenv("BUCKET_NAME")

def get_bucket_region(bucket):
    """Get the actual region of an S3 bucket."""
    try:
        temp_client = boto3.client("s3", region_name="us-east-1")
        if aws_access_key_id and aws_secret_access_key:
            temp_client = boto3.client(
                "s3",
                region_name="us-east-1",
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )
        location = temp_client.get_bucket_location(Bucket=bucket)
        return location.get("LocationConstraint") or "us-east-1"
    except Exception:
        return aws_region

bucket_region = get_bucket_region(bucket_name) if bucket_name else aws_region

if aws_access_key_id and aws_secret_access_key:
    s3 = boto3.client(
        "s3",
        region_name=bucket_region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
else:
    s3 = boto3.client("s3", region_name=aws_region)

BUCKET_NAME = bucket_name
AWS_REGION = bucket_region
