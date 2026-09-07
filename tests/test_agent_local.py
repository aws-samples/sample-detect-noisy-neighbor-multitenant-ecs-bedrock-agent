"""Scaffold-level smoke tests for the agent wiring.

A full end-to-end run of the agent loop (with a scripted fake Bedrock model
that emits tool-use turns) belongs in a future iteration, once a
Bedrock-compatible fake model are in place. For now we verify:

- ``build_agent`` returns a Strands Agent with the three tools and the
  system prompt attached.
- The Lambda handler extracts the cluster name from a realistic alarm event
  and constructs a well-formed user message.
"""

from __future__ import annotations

import json
from typing import Any

from agent.agent import build_agent
from agent.prompts import SYSTEM_PROMPT
from lambda_invoker.handler import _build_user_message, _extract_cluster


class _StubModel:
    """Minimal stand-in so build_agent() does not construct a real BedrockModel."""

    stateful: bool = False
    context_window_limit: int | None = None

    def get_config(self) -> dict[str, Any]:  # pragma: no cover
        return {}

    def update_config(self, **_: Any) -> None:  # pragma: no cover
        pass

    async def stream(self, *_: Any, **__: Any) -> Any:  # pragma: no cover
        if False:
            yield None

    async def structured_output(self, *_: Any, **__: Any) -> Any:  # pragma: no cover
        return None


def test_build_agent_registers_three_tools() -> None:
    agent = build_agent(model=_StubModel())
    specs = agent.tool_registry.get_all_tool_specs()
    names = {spec["name"] for spec in specs}
    assert {"list_tenants", "query_metrics", "take_action"} <= names


def test_system_prompt_is_attached() -> None:
    agent = build_agent(model=_StubModel())
    # Strands stores the system prompt on the agent; check that our
    # authored prompt is preserved verbatim.
    prompt = getattr(agent, "system_prompt", None)
    assert prompt == SYSTEM_PROMPT


def test_lambda_handler_extracts_cluster_from_alarm_event() -> None:
    event = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "detail": {
            "alarmName": "shared-cluster-cpu-high",
            "state": {"value": "ALARM", "reason": "Threshold Crossed: 1 datapoint [78.2]"},
            "configuration": {
                "metrics": [
                    {
                        "metricStat": {
                            "metric": {
                                "namespace": "AWS/ECS",
                                "dimensions": {"ClusterName": "shared-cluster"},
                            }
                        }
                    }
                ]
            },
        },
    }
    assert _extract_cluster(event) == "shared-cluster"

    message = _build_user_message(event)
    assert "shared-cluster-cpu-high" in message
    assert "shared-cluster" in message
    assert "Threshold Crossed" in message


def test_lambda_handler_handles_missing_cluster_dimension() -> None:
    event = {"detail": {"alarmName": "x", "state": {"reason": "r"}}}
    assert _extract_cluster(event) is None
    msg = _build_user_message(event)
    assert "<unknown-cluster>" in msg
    # sanity: the event is JSON-serialisable
    json.dumps(event)
