"""Tool 1 — List Tenants.

Reads the tenant registry from DynamoDB. Read-only. The IAM policy attached to
the agent's Lambda scopes ``dynamodb:Scan`` to a single table ARN.
"""

from __future__ import annotations

import logging
from typing import Any

import boto3
from strands import tool

from agent.config import load_config
from agent.models import ListTenantsResult, Tenant

logger = logging.getLogger(__name__)


def _client(region: str) -> Any:
    return boto3.client("dynamodb", region_name=region)


def _row_to_tenant(item: dict[str, dict[str, Any]]) -> Tenant:
    """Convert a DynamoDB attribute-value item into a Tenant model."""
    return Tenant(
        tenant_id=item["tenant_id"]["S"],
        cluster_name=item["cluster_name"]["S"],
        service_name=item["service_name"]["S"],
        tier=item["tier"]["S"],  # type: ignore[arg-type]
        baseline_share=float(item["baseline_share"]["N"]),
    )


@tool
def list_tenants(cluster_name: str) -> dict[str, Any]:
    """Return the tenants running on ``cluster_name``.

    Args:
        cluster_name: ECS cluster name from the alarm context.

    Returns:
        ListTenantsResult as a dict — a list of tenants with their tier,
        cluster, service, and baseline resource share.
    """
    config = load_config()
    logger.info("list_tenants: cluster=%s table=%s", cluster_name, config.tenant_registry_table)

    ddb = _client(config.aws_region)
    # A production registry would use a GSI on cluster_name; for the sample the
    # table is small and a filtered scan is fine. Scoped by IAM to this table.
    response = ddb.scan(
        TableName=config.tenant_registry_table,
        FilterExpression="cluster_name = :c",
        ExpressionAttributeValues={":c": {"S": cluster_name}},
    )
    tenants = [_row_to_tenant(item) for item in response.get("Items", [])]
    return ListTenantsResult(tenants=tenants).model_dump()
