"""A scripted, Bedrock-shaped fake model for driving the Strands agent offline.

The model does not reason — it replays a fixed script of turns. Each turn is
either a tool call or a final text answer. This lets the E2E test exercise the
real Strands event loop (tool dispatch, message assembly, stop conditions)
without Amazon Bedrock.

Event shapes mirror ``strands.types.streaming.StreamEvent`` (modeled on the
Bedrock Converse streaming API).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    tool_input: dict[str, Any]
    tool_use_id: str = "tool-1"


@dataclass
class FinalText:
    text: str


@dataclass
class FakeBedrockModel:
    """Replays ``turns`` one per stream() invocation.

    Each ``turns`` entry is either a ``ToolCall`` (emits a tool_use turn) or a
    ``FinalText`` (emits text and stops with end_turn).
    """

    turns: list[ToolCall | FinalText]
    stateful: bool = False
    context_window_limit: int | None = None
    _idx: int = field(default=0, init=False)

    def get_config(self) -> dict[str, Any]:
        return {}

    def update_config(self, **_: Any) -> None:
        pass

    async def structured_output(self, *_: Any, **__: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def stream(self, *_: Any, **__: Any) -> AsyncIterable[dict[str, Any]]:
        if self._idx >= len(self.turns):
            # Safety: if the loop asks for more than scripted, end the turn.
            turn: ToolCall | FinalText = FinalText("(script exhausted)")
        else:
            turn = self.turns[self._idx]
            self._idx += 1

        yield {"messageStart": {"role": "assistant"}}

        if isinstance(turn, ToolCall):
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {"toolUse": {"name": turn.name, "toolUseId": turn.tool_use_id}},
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": json.dumps(turn.tool_input)}},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {
                "contentBlockStart": {"contentBlockIndex": 0, "start": {}},
            }
            yield {
                "contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": turn.text}},
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}

        yield {
            "metadata": {
                "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
                "metrics": {"latencyMs": 1},
            }
        }
