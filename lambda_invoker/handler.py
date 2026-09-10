"""Lambda handler wired to an EventBridge rule matching CloudWatch alarm events.

Event shape (excerpt) — CloudWatch alarm state change delivered via EventBridge::

    {
      "source": "aws.cloudwatch",
      "detail-type": "CloudWatch Alarm State Change",
      "detail": {
        "alarmName": "...",
        "state": {"value": "ALARM", "reason": "..."},
        "configuration": {
          "metrics": [{"metricStat": {"metric": {
              "namespace": "AWS/ECS",
              "dimensions": {"ClusterName": "shared-cluster"}
          }}}]
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.agent import invoke

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _extract_cluster(event: dict[str, Any]) -> str | None:
    """Best-effort extraction of the ECS cluster name from an alarm event."""
    try:
        metrics = event["detail"]["configuration"]["metrics"]
        for m in metrics:
            dims = m.get("metricStat", {}).get("metric", {}).get("dimensions", {})
            if "ClusterName" in dims:
                return str(dims["ClusterName"])
    except (KeyError, TypeError):
        return None
    return None


def _build_user_message(event: dict[str, Any]) -> str:
    detail = event.get("detail", {})
    alarm = detail.get("alarmName", "<unknown-alarm>")
    reason = detail.get("state", {}).get("reason", "no reason provided")
    cluster = _extract_cluster(event) or "<unknown-cluster>"
    return (
        f"Alarm {alarm!r} entered ALARM state for cluster {cluster!r}. "
        f"Reason: {reason}. Identify the noisy tenant and take the appropriate "
        f"first-line action."
    )


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Entry point for AWS Lambda."""
    logger.info("received event: %s", json.dumps(event)[:2048])
    user_message = _build_user_message(event)
    output = invoke(user_message)
    logger.info("agent output: %s", output[:2048])
    return {"statusCode": 200, "body": output}
