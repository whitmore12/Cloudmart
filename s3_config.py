# Nickodemus made this file and code
import os
import boto3  # type: ignore[import-not-found]

# Use explicit credentials if provided, otherwise fall back to IAM role (for EB/EC2)
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_REGION", "us-east-1")

if aws_access_key_id and aws_secret_access_key:
    s3 = boto3.client(
        "s3",
        region_name=aws_region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
else:
    # Use IAM role (recommended for EB)
    s3 = boto3.client("s3", region_name=aws_region)

BUCKET_NAME = os.getenv("BUCKET_NAME")
AWS_REGION = aws_region
