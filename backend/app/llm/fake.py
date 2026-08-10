"""Deterministic fake provider.

Two jobs. In tests it replays a scripted list of responses, so orchestration
logic is verified without a network call. Outside tests it synthesises a
schema-valid artifact from `output_format`, which lets the whole pipeline —
state machine, gates, event stream, UI — be demonstrated with no API key and
no cost. It is not a model: it produces structurally valid, semantically empty
output, and says so.
"""

from __future__ import annotations

import json
from typing import Any

from .base import LLMRequest, LLMResponse, Usage

PLACEHOLDER = "[fake provider] no model was called; this value is a placeholder."


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def synthesize(schema: dict[str, Any], root: dict[str, Any] | None = None, depth: int = 0) -> Any:
    """Smallest value that satisfies `schema`. Recursion is depth-bounded."""
    root = root if root is not None else schema
    if depth > 8:
        return None
    schema = _resolve(schema, root)

    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    for key in ("anyOf", "oneOf", "allOf"):
        if schema.get(key):
            return synthesize(schema[key][0], root, depth + 1)

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")

    if kind == "object":
        properties = schema.get("properties", {})
        return {
            name: synthesize(sub, root, depth + 1) for name, sub in properties.items()
        }
    if kind == "array":
        items = schema.get("items")
        return [synthesize(items, root, depth + 1)] if items else []
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return PLACEHOLDER


class FakeLLMClient:
    """Replays `script`; falls back to schema synthesis once it is exhausted."""

    provider = "fake"

    def __init__(self, script: list[LLMResponse] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.script:
            response = self.script.pop(0)
            return response

        if request.output_format is not None:
            payload = synthesize(request.output_format.get("schema", {}))
            text = json.dumps(payload, ensure_ascii=False)
        else:
            text = PLACEHOLDER

        return LLMResponse(
            content=[{"type": "text", "text": text}],
            stop_reason="end_turn",
            usage=Usage(input_tokens=0, output_tokens=0),
            model="fake",
        )


def scripted_text(text: str, *, stop_reason: str = "end_turn") -> LLMResponse:
    return LLMResponse(
        content=[{"type": "text", "text": text}],
        stop_reason=stop_reason,
        usage=Usage(input_tokens=10, output_tokens=10),
        model="fake",
    )


def scripted_json(payload: Any) -> LLMResponse:
    return scripted_text(json.dumps(payload, ensure_ascii=False))


def scripted_tool_call(name: str, tool_input: dict[str, Any], call_id: str = "toolu_fake") -> LLMResponse:
    return LLMResponse(
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}],
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=10),
        model="fake",
    )
