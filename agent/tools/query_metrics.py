"""Tool 2 — Query Metrics.

Runs a single PromQL query against Amazon Managed Service for Prometheus. The
call is signed with SigV4 (service ``aps``). Read-only: only the ``/api/v1/query``
endpoint is used.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from strands import tool

from agent.config import load_config
from agent.models import MetricSample, PromQLQuery, QueryMetricsResult

logger = logging.getLogger(__name__)

# AMP responses can be large; refuse anything past this to keep the agent
# context bounded.
_MAX_SAMPLES = 200
_HTTP_TIMEOUT_SECONDS = 10


def _sign_and_get(url: str, params: dict[str, str], region: str) -> requests.Response:
    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:  # pragma: no cover — defensive
        raise RuntimeError("No AWS credentials available for SigV4 signing")

    req = AWSRequest(method="GET", url=url, params=params)
    SigV4Auth(credentials, "aps", region).add_auth(req)
    prepared = req.prepare()
    return requests.get(
        prepared.url,
        headers=dict(prepared.headers),
        timeout=_HTTP_TIMEOUT_SECONDS,
    )


def _parse_response(payload: dict[str, Any]) -> list[MetricSample]:
    """Parse the standard Prometheus /query response shape."""
    if payload.get("status") != "success":
        raise RuntimeError(f"AMP query failed: {payload.get('error', 'unknown')}")

    data = payload.get("data", {})
    result_type = data.get("resultType")
    results = data.get("result", [])

    samples: list[MetricSample] = []
    if result_type == "vector":
        for entry in results[:_MAX_SAMPLES]:
            metric = entry.get("metric", {})
            ts, val = entry.get("value", [0, "nan"])
            samples.append(
                MetricSample(labels=metric, value=float(val), timestamp=float(ts))
            )
    elif result_type == "scalar":
        ts, val = results
        samples.append(MetricSample(labels={}, value=float(val), timestamp=float(ts)))
    else:
        # matrix / string — surface a clear error rather than silently return []
        raise RuntimeError(f"Unsupported result type from AMP: {result_type!r}")
    return samples


@tool
def query_metrics(query: str) -> dict[str, Any]:
    """Run a single PromQL instant query against Amazon Managed Prometheus.

    Args:
        query: A single PromQL expression. Read-only — no remote_write.

    Returns:
        QueryMetricsResult as a dict.
    """
    validated = PromQLQuery(query=query)
    config = load_config()
    url = urljoin(config.amp_workspace_url.rstrip("/") + "/", "api/v1/query")
    logger.info("query_metrics: url=%s query=%s", url, validated.query)

    response = _sign_and_get(url, {"query": validated.query}, config.aws_region)
    response.raise_for_status()
    samples = _parse_response(response.json())
    return QueryMetricsResult(samples=samples).model_dump()
