"""Offline end-to-end tests: the real Strands agent loop driven by a scripted
fake Bedrock model, against moto (DynamoDB/ECS/SNS) and mocked AMP (responses).

These validate that the agent's tool-call sequence produces the correct infra
outcome for two canonical scenarios:

- traffic spike  -> scale the noisy tenant's service (dev auto-remediates)
- stuck requests -> alert only, no scaling
"""

from __future__ import annotations

import boto3
import responses

from agent.agent import invoke
from tests.fake_model import FakeBedrockModel, FinalText, ToolCall

_AMP_URL = "https://aps-workspaces.example/workspaces/ws-1/api/v1/query"


def _spike_vector() -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"tenant_id": "tenant-a"}, "value": [1700000000.0, "0.73"]},
                {"metric": {"tenant_id": "tenant-b"}, "value": [1700000000.0, "0.15"]},
            ],
        },
    }


@responses.activate
def test_spike_scales_noisy_tenant(
    registry: str,
    ecs_service: tuple[str, str],
    cluster_name: str,
    sns_topic: str,
) -> None:
    responses.add(responses.GET, _AMP_URL, json=_spike_vector(), status=200)
    cluster, service = ecs_service

    model = FakeBedrockModel(
        turns=[
            ToolCall("list_tenants", {"cluster_name": cluster}),
            ToolCall(
                "query_metrics",
                {"query": "sum by (tenant_id) (rate(http_requests_total[5m]))"},
            ),
            ToolCall(
                "take_action",
                {
                    "tenant_id": "tenant-a",
                    "cluster_name": cluster,
                    "service_name": service,
                    "desired_count": 8,
                    "reason": "tenant-a at 73% vs 50% baseline; steady 5x spike",
                },
            ),
            FinalText("Scaled tenant-a's service to 8 tasks due to a legitimate spike."),
        ]
    )

    output = invoke("alarm fired for shared-cluster", model=model)
    assert "tenant-a" in output

    ecs = boto3.client("ecs", region_name="us-east-1")
    described = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
    assert described["desiredCount"] == 8


@responses.activate
def test_stuck_requests_alert_only(
    registry: str,
    ecs_service: tuple[str, str],
    cluster_name: str,
    sns_topic: str,
) -> None:
    responses.add(responses.GET, _AMP_URL, json=_spike_vector(), status=200)
    cluster, service = ecs_service

    model = FakeBedrockModel(
        turns=[
            ToolCall("list_tenants", {"cluster_name": cluster}),
            ToolCall(
                "query_metrics",
                {
                    "query": "histogram_quantile(0.95, sum by (tenant_id, le) "
                    "(rate(http_request_duration_seconds_bucket[5m])))"
                },
            ),
            ToolCall(
                "take_action",
                {
                    "tenant_id": "tenant-a",
                    "cluster_name": cluster,
                    "service_name": service,
                    "desired_count": 2,
                    "reason": "rising p95 with flat throughput — stuck requests",
                    "alert_only": True,
                },
            ),
            FinalText("Alerted on tenant-a: stuck requests, scaling would not help."),
        ]
    )

    output = invoke("alarm fired for shared-cluster", model=model)
    assert "tenant-a" in output

    # Alert-only must NOT change desiredCount.
    ecs = boto3.client("ecs", region_name="us-east-1")
    described = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
    assert described["desiredCount"] == 2
