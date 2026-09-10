"""Environment-driven configuration for the agent and its tools.

All AWS resource names/ARNs come from environment variables set by the IaC
stack. Tests inject a fabricated ``Config`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum


class Environment(StrEnum):
    """Deployment environment. Governs whether take_action auto-remediates."""

    DEV = "dev"
    PROD = "prod"


# Bounds enforced by take_action regardless of what the model returns.
DEFAULT_MIN_DESIRED_COUNT = 1
DEFAULT_MAX_DESIRED_COUNT = 20


@dataclass(frozen=True)
class Config:
    environment: Environment
    aws_region: str
    bedrock_model_id: str
    tenant_registry_table: str
    amp_workspace_url: str
    sns_topic_arn: str | None
    min_desired_count: int = DEFAULT_MIN_DESIRED_COUNT
    max_desired_count: int = DEFAULT_MAX_DESIRED_COUNT

    def __post_init__(self) -> None:
        if self.min_desired_count < 1:
            raise ValueError("min_desired_count must be >= 1")
        if self.max_desired_count < self.min_desired_count:
            raise ValueError("max_desired_count must be >= min_desired_count")
        if self.environment is Environment.PROD and not self.sns_topic_arn:
            raise ValueError("SNS topic ARN is required when environment=prod")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


def load_config() -> Config:
    """Build a Config from process environment variables."""
    environment = Environment(os.environ.get("ENV", Environment.DEV.value))
    return Config(
        environment=environment,
        aws_region=_required("AWS_REGION"),
        bedrock_model_id=os.environ.get(
            "BEDROCK_MODEL_ID",
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        ),
        tenant_registry_table=_required("TENANT_REGISTRY_TABLE"),
        amp_workspace_url=_required("AMP_WORKSPACE_URL"),
        sns_topic_arn=os.environ.get("SNS_TOPIC_ARN"),
        min_desired_count=_int("MIN_DESIRED_COUNT", DEFAULT_MIN_DESIRED_COUNT),
        max_desired_count=_int("MAX_DESIRED_COUNT", DEFAULT_MAX_DESIRED_COUNT),
    )
