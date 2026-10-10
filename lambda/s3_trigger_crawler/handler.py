"""Lambda: auto-trigger or auto-create Glue Crawlers when data lands in S3.

Behavior:
- Extracts the top-level prefix (folder) from the S3 key.
- If a crawler already exists for that prefix → starts it.
- If no crawler exists → creates a new Glue database + crawler, then starts it.

Naming convention:
  The two KNOWN prefixes are pinned to the CloudFormation-managed names
  (CFN is the single source of truth), and the Lambda STARTS the existing
  CFN crawler rather than creating a duplicate database/crawler:
    prefix "library-data/" → DB "project_library_db", crawler "project-library-crawler"
    prefix "cars-data/"    → DB "project_cars_db",    crawler "project-cars-crawler"
  UNKNOWN prefixes keep the generic sanitize-based behavior (create on demand):
    prefix "sales/"        → DB "project_sales_db",   crawler "project-sales-crawler"
"""

import json
import logging
import os
import re
import urllib.parse

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

glue = boto3.client("glue")

# The two prefixes provisioned by CloudFormation. CFN owns these crawlers and
# databases, so we must reuse its exact names instead of deriving our own via
# _sanitize_name — otherwise the Lambda would create duplicate catalogs
# (project_cars_data_db / project-cars-data-crawler) alongside the CFN ones
# (project_cars_db / project-cars-crawler). Map: prefix -> (db_name, crawler_name).
KNOWN_PREFIXES = {
    "cars-data": ("project_cars_db", "project-cars-crawler"),
    "library-data": ("project_library_db", "project-library-crawler"),
}

# Environment variables set by CloudFormation
CRAWLER_ROLE_ARN = os.environ["CRAWLER_ROLE_ARN"]
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "")
REGION = os.environ.get("AWS_REGION", "eu-north-1")


def _sanitize_name(prefix: str) -> str:
    """Convert an S3 prefix like 'library-data/' to a clean identifier."""
    name = prefix.strip("/").lower()
    # Replace non-alphanumeric chars with underscores
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def _db_name(prefix: str) -> str:
    return f"project_{_sanitize_name(prefix)}_db"


def _crawler_name(prefix: str) -> str:
    sanitized = _sanitize_name(prefix).replace("_", "-")
    return f"project-{sanitized}-crawler"


def _crawler_exists(name: str) -> bool:
    try:
        glue.get_crawler(Name=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            return False
        raise


def _database_exists(name: str) -> bool:
    try:
        glue.get_database(Name=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            return False
        raise


def _create_database(db_name: str, description: str) -> None:
    logger.info("Creating Glue database: %s", db_name)
    glue.create_database(
        DatabaseInput={
            "Name": db_name,
            "Description": description,
        }
    )


def _create_crawler(crawler_name: str, db_name: str, s3_path: str) -> None:
    logger.info("Creating Glue crawler: %s → %s", crawler_name, s3_path)
    glue.create_crawler(
        Name=crawler_name,
        Role=CRAWLER_ROLE_ARN,
        DatabaseName=db_name,
        Targets={"S3Targets": [{"Path": s3_path}]},
        SchemaChangePolicy={
            "UpdateBehavior": "UPDATE_IN_DATABASE",
            "DeleteBehavior": "LOG",
        },
        Tags={"ManagedBy": "s3-trigger-lambda"},
    )


def _start_crawler(crawler_name: str) -> None:
    try:
        glue.start_crawler(Name=crawler_name)
        logger.info("Started crawler: %s", crawler_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "CrawlerRunningException":
            logger.info("Crawler %s is already running — skipping.", crawler_name)
        else:
            raise


def handler(event, context):
    """Process S3 event notifications."""
    logger.debug("Event: %s", json.dumps(event))

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        # Extract top-level prefix (first path segment)
        parts = key.split("/")
        if len(parts) < 2:
            logger.info("Skipping root-level object: %s", key)
            continue

        prefix = parts[0]
        s3_path = f"s3://{bucket}/{prefix}/"

        # For the two CFN-managed prefixes, pin to the CloudFormation names and
        # just START the existing crawler (no duplicate db/crawler creation).
        # Unknown prefixes keep the generic sanitize-based create-then-start path.
        known = KNOWN_PREFIXES.get(prefix)
        if known is not None:
            db_name, crawler_name = known
        else:
            crawler_name = _crawler_name(prefix)
            db_name = _db_name(prefix)

        logger.info(
            "Processing: bucket=%s prefix=%s crawler=%s db=%s known=%s",
            bucket, prefix, crawler_name, db_name, known is not None,
        )

        if known is not None:
            # CFN owns the crawler/database. Start it if present; only fall back
            # to creating resources if the expected CFN crawler is missing.
            if _crawler_exists(crawler_name):
                _start_crawler(crawler_name)
                continue
            logger.warning(
                "Expected CFN crawler %s not found — creating as a fallback.",
                crawler_name,
            )

        # Generic path (unknown prefix, or known-prefix fallback):
        # ensure database + crawler exist, then start.
        if not _database_exists(db_name):
            _create_database(db_name, f"Auto-created database for s3://{bucket}/{prefix}/")

        if not _crawler_exists(crawler_name):
            _create_crawler(crawler_name, db_name, s3_path)

        _start_crawler(crawler_name)

    return {"statusCode": 200, "body": "OK"}
