from __future__ import annotations

import pytest
import responses

from agent.models import PromQLQuery
from agent.tools.query_metrics import query_metrics

_AMP_URL = "https://aps-workspaces.example/workspaces/ws-1/api/v1/query"


@responses.activate
def test_parses_vector_response(aws: None) -> None:
    responses.add(
        responses.GET,
        _AMP_URL,
        json={
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"tenant_id": "tenant-a"},
                        "value": [1700000000.0, "0.73"],
                    },
                    {
                        "metric": {"tenant_id": "tenant-b"},
                        "value": [1700000000.0, "0.15"],
                    },
                ],
            },
        },
        status=200,
    )
    out = query_metrics(query="sum by (tenant_id) (rate(http_requests_total[5m]))")  # type: ignore[call-arg]
    values = {s["labels"]["tenant_id"]: s["value"] for s in out["samples"]}
    assert values == {"tenant-a": 0.73, "tenant-b": 0.15}


def test_rejects_query_with_control_chars() -> None:
    with pytest.raises(ValueError, match="control characters"):
        PromQLQuery(query="foo\nbar")


@responses.activate
def test_raises_when_amp_reports_failure(aws: None) -> None:
    responses.add(
        responses.GET,
        _AMP_URL,
        json={"status": "error", "error": "parse error"},
        status=200,
    )
    with pytest.raises(RuntimeError, match="AMP query failed"):
        query_metrics(query="up")  # type: ignore[call-arg]
