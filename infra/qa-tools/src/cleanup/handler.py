"""QA cleanup Lambda — clears DynamoDB test data on demand.

POST /qa/cleanup with a JSON body:
    {
        "table_name": "porth-users-dev",   // required
        "prefix": "TENANT#test-tenant-001"  // optional PK prefix filter
    }

If prefix is omitted, ALL items in the table are deleted.
Returns: { "deleted": N, "table": "..." }

Safety:
- Only deployed to dev/staging (SAM template restricts Environment param)
- Rejects table names that don't start with 'porth-'
- Rejects table names containing '-prod'
- Environment-bound: table name must contain the deployed env suffix
- AWS_IAM auth on the API Gateway route
- Logs every invocation with table name and item count
"""

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point — called by API Gateway."""
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON body"})

    table_name = body.get("table_name")
    prefix = body.get("prefix")  # optional PK prefix filter

    # --- Validation -----------------------------------------------------------
    if not table_name:
        return _response(400, {"error": "table_name is required"})

    if not table_name.startswith("porth-"):
        return _response(400, {
            "error": f"Refused: table name '{table_name}' does not start with 'porth-'"
        })

    # Extra safety: reject anything that looks like prod
    if "-prod" in table_name:
        return _response(403, {
            "error": "Refused: cannot clean production tables"
        })

    # Environment-bound safety: require table_name to match the deployed env
    porth_env = os.environ.get("PORTH_ENV")
    if not porth_env:
        return _response(500, {
            "error": "Server misconfiguration: PORTH_ENV is not set"
        })

    expected_suffix = f"-{porth_env}"
    if expected_suffix not in table_name:
        return _response(403, {
            "error": (
                f"Refused: table name '{table_name}' does not match "
                f"environment suffix '{expected_suffix}'"
            )
        })

    # --- Scan and delete ------------------------------------------------------
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-east-1"))
    dynamodb = boto3.resource("dynamodb", region_name=region)

    try:
        table = dynamodb.Table(table_name)
        # Get the key schema so we know which attributes to use for delete
        key_attrs = [k["AttributeName"] for k in table.key_schema]
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        logger.error("DynamoDB error describing table %s: %s %s", table_name, code, msg)
        status = 404 if code == "ResourceNotFoundException" else 500
        return _response(status, {"error": f"DynamoDB error: {code} — {msg}"})

    logger.info(
        "QA cleanup starting: table=%s prefix=%s key_attrs=%s",
        table_name, prefix, key_attrs,
    )

    # Only fetch key attributes to reduce read throughput and memory
    projection = ", ".join(f"#k{i}" for i in range(len(key_attrs)))
    attr_names = {f"#k{i}": attr for i, attr in enumerate(key_attrs)}

    scan_kwargs = {
        "ProjectionExpression": projection,
        "ExpressionAttributeNames": attr_names,
    }
    if prefix:
        pk_attr = key_attrs[0]
        # Find which alias maps to the PK
        pk_alias = next(k for k, v in attr_names.items() if v == pk_attr)
        scan_kwargs["FilterExpression"] = Attr(pk_attr).begins_with(prefix)

    deleted = 0
    last_key = None

    try:
        while True:
            if last_key:
                scan_kwargs["ExclusiveStartKey"] = last_key

            resp = table.scan(**scan_kwargs)
            items = resp.get("Items", [])

            if items:
                with table.batch_writer() as batch:
                    for item in items:
                        key = {k: item[k] for k in key_attrs}
                        batch.delete_item(Key=key)
                # Only count after batch completes successfully
                deleted += len(items)

            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        logger.error(
            "DynamoDB error during cleanup of %s: %s %s (deleted %d so far)",
            table_name, code, msg, deleted,
        )
        status = 429 if code == "ProvisionedThroughputExceededException" else 500
        return _response(status, {
            "error": f"DynamoDB error: {code} — {msg}",
            "deleted_before_error": deleted,
            "table": table_name,
        })

    logger.info("QA cleanup complete: table=%s deleted=%d", table_name, deleted)

    return _response(200, {
        "deleted": deleted,
        "table": table_name,
        "prefix": prefix,
    })


def _response(status_code: int, body: dict) -> dict:
    """Build an API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
