"""Shared fixtures.

Every fixture sets up in-process AWS emulation with moto and constructs a
``Config`` from the environment so the tools' ``load_config`` finds the same
resources.
"""

from __future__ import annotations

from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

_REGION = "us-east-1"
_TABLE = "tenant-registry-test"
_TOPIC = "noisy-neighbor-proposals-test"
_CLUSTER = "shared-cluster"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", _REGION)
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)
    # boto3's default credential lookup — moto accepts anything.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("TENANT_REGISTRY_TABLE", _TABLE)
    monkeypatch.setenv("AMP_WORKSPACE_URL", "https://aps-workspaces.example/workspaces/ws-1")
    monkeypatch.setenv("MAX_DESIRED_COUNT", "20")


@pytest.fixture
def aws() -> Iterator[None]:
    with mock_aws():
        yield


@pytest.fixture
def registry(aws: None) -> str:
    ddb = boto3.client("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName=_TABLE,
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.put_item(
        TableName=_TABLE,
        Item={
            "tenant_id": {"S": "tenant-a"},
            "cluster_name": {"S": _CLUSTER},
            "service_name": {"S": "svc-a"},
            "tier": {"S": "standard"},
            "baseline_share": {"N": "0.5"},
        },
    )
    ddb.put_item(
        TableName=_TABLE,
        Item={
            "tenant_id": {"S": "tenant-b"},
            "cluster_name": {"S": _CLUSTER},
            "service_name": {"S": "svc-b"},
            "tier": {"S": "premium"},
            "baseline_share": {"N": "0.5"},
        },
    )
    return _TABLE


@pytest.fixture
def ecs_service(aws: None) -> tuple[str, str]:
    ecs = boto3.client("ecs", region_name=_REGION)
    ecs.create_cluster(clusterName=_CLUSTER)
    ecs.register_task_definition(
        family="svc-a",
        containerDefinitions=[{"name": "app", "image": "example:1", "memory": 256}],
    )
    ecs.create_service(
        cluster=_CLUSTER,
        serviceName="svc-a",
        taskDefinition="svc-a",
        desiredCount=2,
    )
    return _CLUSTER, "svc-a"


@pytest.fixture
def sns_topic(aws: None, monkeypatch: pytest.MonkeyPatch) -> str:
    sns = boto3.client("sns", region_name=_REGION)
    arn = sns.create_topic(Name=_TOPIC)["TopicArn"]
    monkeypatch.setenv("SNS_TOPIC_ARN", arn)
    return arn


@pytest.fixture
def prod_env(monkeypatch: pytest.MonkeyPatch, sns_topic: str) -> None:
    # sns_topic sets SNS_TOPIC_ARN; flipping ENV last is important.
    del sns_topic  # only needed for its side-effect
    monkeypatch.setenv("ENV", "prod")


@pytest.fixture
def cluster_name() -> str:
    return _CLUSTER


@pytest.fixture(autouse=True)
def _reset_env_after(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Ensure any stray env we didn't set (SNS_TOPIC_ARN in dev tests) starts clean.
    for k in ("SNS_TOPIC_ARN",):
        monkeypatch.delenv(k, raising=False)
    yield
