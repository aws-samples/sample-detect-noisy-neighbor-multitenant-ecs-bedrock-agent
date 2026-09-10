"""Typed request/response models for the agent's tools and outputs.

Using Pydantic keeps tool inputs validated and gives the Strands framework a
schema it can expose to the model. Every field has an explicit type and a
short description that the model sees.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Tenant(BaseModel):
    """One row of the tenant registry."""

    tenant_id: str = Field(..., description="Stable identifier used as the metric label")
    cluster_name: str = Field(..., description="ECS cluster the tenant runs on")
    service_name: str = Field(..., description="ECS service to scale for this tenant")
    tier: Literal["standard", "premium", "enterprise"] = Field(
        ..., description="Tenant tier — affects baseline share and priority"
    )
    baseline_share: float = Field(
        ..., ge=0.0, le=1.0, description="Expected fraction of cluster resources under normal load"
    )


class ListTenantsResult(BaseModel):
    tenants: list[Tenant]


class PromQLQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=1024, description="A single PromQL expression")

    @field_validator("query")
    @classmethod
    def _reject_dangerous(cls, v: str) -> str:
        # Defense-in-depth: PromQL is read-only, but we still reject obvious
        # abuse patterns (control chars, embedded newlines that break the URL).
        if any(ch in v for ch in ("\n", "\r", "\x00")):
            raise ValueError("query must be a single line without control characters")
        return v


class MetricSample(BaseModel):
    labels: dict[str, str]
    value: float
    timestamp: float


class QueryMetricsResult(BaseModel):
    samples: list[MetricSample]


class ScaleProposal(BaseModel):
    tenant_id: str
    cluster_name: str
    service_name: str
    desired_count: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=1024)


class TakeActionResult(BaseModel):
    action: Literal["scaled", "alerted", "no_op"]
    applied: bool = Field(
        ..., description="True when infra changed; false when only a proposal was published"
    )
    detail: str


class AgentSummary(BaseModel):
    """Structured summary the agent returns to the invoker."""

    noisy_tenant: str | None = None
    likely_cause: str
    action_taken: TakeActionResult
    reasoning: str
