"""Agent factory.

The Strands ``Agent`` is built here and invoked by the Lambda handler with the
CloudWatch alarm payload. Tools are declared explicitly — we do not enable
tool auto-discovery.
"""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent
from strands.models import BedrockModel

from agent.config import load_config
from agent.prompts import SYSTEM_PROMPT
from agent.tools import list_tenants, query_metrics, take_action

logger = logging.getLogger(__name__)


def build_agent(model: Any | None = None) -> Agent:
    """Return a configured Strands Agent.

    Args:
        model: An optional pre-built model. Tests pass a fake model here;
            production leaves it ``None`` so a Bedrock model is constructed
            from configuration.
    """
    cfg = load_config()
    if model is None:
        model = BedrockModel(
            model_id=cfg.bedrock_model_id,
            region_name=cfg.aws_region,
        )
    return Agent(
        model=model,
        tools=[list_tenants, query_metrics, take_action],
        system_prompt=SYSTEM_PROMPT,
    )


def invoke(user_message: str, model: Any | None = None) -> str:
    """Invoke the agent with a single user message and return its text output.

    The Strands ``Agent`` is callable and returns a response object; we coerce
    to ``str`` so the Lambda handler can log/return it verbatim.
    """
    agent = build_agent(model=model)
    logger.info("invoking agent")
    response = agent(user_message)
    return str(response)
