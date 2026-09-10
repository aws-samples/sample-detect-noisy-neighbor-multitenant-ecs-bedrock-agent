from __future__ import annotations

import json

import boto3

from agent.tools.take_action import take_action


def test_dev_scales_ecs_service(
    registry: str,
    ecs_service: tuple[str, str],
    cluster_name: str,
) -> None:
    cluster, service = ecs_service
    out = take_action(  # type: ignore[call-arg]
        tenant_id="tenant-a",
        cluster_name=cluster,
        service_name=service,
        desired_count=8,
        reason="5x steady traffic spike",
    )
    assert out["action"] == "scaled"
    assert out["applied"] is True

    ecs = boto3.client("ecs", region_name="us-east-1")
    described = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
    assert described["desiredCount"] == 8


def test_dev_clamps_desired_count(
    registry: str,
    ecs_service: tuple[str, str],
) -> None:
    cluster, service = ecs_service
    take_action(  # type: ignore[call-arg]
        tenant_id="tenant-a",
        cluster_name=cluster,
        service_name=service,
        desired_count=999,
        reason="uncapped",
    )
    ecs = boto3.client("ecs", region_name="us-east-1")
    described = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
    assert described["desiredCount"] == 20  # MAX_DESIRED_COUNT


def test_refuses_unknown_tenant(
    registry: str,
    ecs_service: tuple[str, str],
) -> None:
    cluster, service = ecs_service
    out = take_action(  # type: ignore[call-arg]
        tenant_id="tenant-fabricated",
        cluster_name=cluster,
        service_name=service,
        desired_count=5,
        reason="hallucinated",
    )
    assert out["action"] == "no_op"
    assert out["applied"] is False


def test_prod_publishes_proposal_instead_of_scaling(
    prod_env: None,
    registry: str,
    ecs_service: tuple[str, str],
    sns_topic: str,
) -> None:
    cluster, service = ecs_service
    out = take_action(  # type: ignore[call-arg]
        tenant_id="tenant-a",
        cluster_name=cluster,
        service_name=service,
        desired_count=6,
        reason="prod-approval-path",
    )
    assert out["action"] == "alerted"
    assert out["applied"] is False
    assert sns_topic in out["detail"]

    # Confirm ECS service was NOT scaled in prod.
    ecs = boto3.client("ecs", region_name="us-east-1")
    described = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
    assert described["desiredCount"] == 2  # unchanged


def test_alert_only_publishes_without_scaling(
    registry: str,
    ecs_service: tuple[str, str],
    sns_topic: str,
) -> None:
    cluster, service = ecs_service
    out = take_action(  # type: ignore[call-arg]
        tenant_id="tenant-a",
        cluster_name=cluster,
        service_name=service,
        desired_count=6,
        reason="rising p95 with flat throughput",
        alert_only=True,
    )
    assert out["action"] == "alerted"
    assert out["applied"] is False
    ecs = boto3.client("ecs", region_name="us-east-1")
    described = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
    assert described["desiredCount"] == 2

    # The proposal payload should be a well-formed JSON body — sanity check by
    # round-tripping the "detail" line's shape.
    assert "awaiting" in out["detail"]
    json.dumps(out)  # serializable
