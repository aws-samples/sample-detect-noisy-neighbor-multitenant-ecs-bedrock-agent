"""Tool 3 — Take Action.

Two actions, dispatched by the ``ENV`` config:

- ``dev``: call ``ecs:UpdateService`` with a clamped ``desiredCount``.
- ``prod``: publish a structured remediation proposal to SNS and stop.

Never both. The choice is enforced code-side, not model-side.

The tool also refuses to act on a ``tenant_id`` that is not present in the
tenant registry — this guards against a jailbroken model fabricating an id.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from strands import tool

from agent.config import Config, Environment, load_config
from agent.models import ScaleProposal, TakeActionResult
from agent.tools.list_tenants import list_tenants

logger = logging.getLogger(__name__)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _tenant_is_registered(cfg: Config, tenant_id: str, cluster_name: str) -> bool:
    result = list_tenants(cluster_name=cluster_name)  # type: ignore[call-arg]
    return any(t["tenant_id"] == tenant_id for t in result["tenants"])


def _scale_service(cfg: Config, proposal: ScaleProposal) -> TakeActionResult:
    ecs = boto3.client("ecs", region_name=cfg.aws_region)
    ecs.update_service(
        cluster=proposal.cluster_name,
        service=proposal.service_name,
        desiredCount=proposal.desired_count,
    )
    return TakeActionResult(
        action="scaled",
        applied=True,
        detail=(
            f"Scaled {proposal.service_name} on {proposal.cluster_name} to "
            f"{proposal.desired_count} tasks for tenant {proposal.tenant_id}."
        ),
    )


def _publish_proposal(cfg: Config, proposal: ScaleProposal) -> TakeActionResult:
    assert cfg.sns_topic_arn is not None  # enforced by Config.__post_init__
    sns = boto3.client("sns", region_name=cfg.aws_region)
    payload = {
        "type": "noisy-neighbor-remediation-proposal",
        "environment": cfg.environment.value,
        "tenant_id": proposal.tenant_id,
        "cluster_name": proposal.cluster_name,
        "service_name": proposal.service_name,
        "proposed_desired_count": proposal.desired_count,
        "reason": proposal.reason,
    }
    sns.publish(
        TopicArn=cfg.sns_topic_arn,
        Subject=f"[approve] scale {proposal.service_name} for tenant {proposal.tenant_id}",
        Message=json.dumps(payload),
        MessageAttributes={
            "tenant_id": {"DataType": "String", "StringValue": proposal.tenant_id},
            "action": {"DataType": "String", "StringValue": "scale"},
        },
    )
    return TakeActionResult(
        action="alerted",
        applied=False,
        detail=(
            f"Published remediation proposal to {cfg.sns_topic_arn} — awaiting "
            f"human approval to scale {proposal.service_name} to "
            f"{proposal.desired_count} tasks."
        ),
    )


@tool
def take_action(
    tenant_id: str,
    cluster_name: str,
    service_name: str,
    desired_count: int,
    reason: str,
    alert_only: bool = False,
) -> dict[str, Any]:
    """Apply a first-line remediation for the noisy tenant.

    In ``dev``, this scales the ECS service (or alerts if ``alert_only``). In
    ``prod``, this always publishes a proposal to SNS for human approval —
    even for scale actions.

    Args:
        tenant_id: Tenant identifier from list_tenants. Must be in the registry.
        cluster_name: ECS cluster name.
        service_name: ECS service to scale.
        desired_count: Proposed desiredCount. Clamped to [min, max] from config.
        reason: Short human-readable explanation the reviewer will see.
        alert_only: True when the agent decided scaling is not appropriate
            (e.g. stuck requests). Publishes an alert with no scale proposal.

    Returns:
        TakeActionResult as a dict.
    """
    cfg = load_config()

    if not _tenant_is_registered(cfg, tenant_id, cluster_name):
        return TakeActionResult(
            action="no_op",
            applied=False,
            detail=f"Refused: tenant {tenant_id!r} is not in the registry for {cluster_name}.",
        ).model_dump()

    clamped = _clamp(desired_count, cfg.min_desired_count, cfg.max_desired_count)
    if alert_only:
        # Alert-only is always SNS regardless of environment, and never scales.
        if cfg.sns_topic_arn is None:
            return TakeActionResult(
                action="no_op",
                applied=False,
                detail="Alert-only requested but SNS_TOPIC_ARN is not configured.",
            ).model_dump()
        proposal = ScaleProposal(
            tenant_id=tenant_id,
            cluster_name=cluster_name,
            service_name=service_name,
            desired_count=clamped,
            reason=f"alert-only: {reason}",
        )
        result = _publish_proposal(cfg, proposal)
        logger.info("take_action alert-only: %s", result.detail)
        return result.model_dump()

    proposal = ScaleProposal(
        tenant_id=tenant_id,
        cluster_name=cluster_name,
        service_name=service_name,
        desired_count=clamped,
        reason=reason,
    )
    if cfg.environment is Environment.DEV:
        result = _scale_service(cfg, proposal)
    else:
        result = _publish_proposal(cfg, proposal)
    logger.info("take_action: %s", result.detail)
    return result.model_dump()
