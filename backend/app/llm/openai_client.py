"""OpenAI-compatible provider (llama.cpp, vLLM, SGLang, LM Studio, Ollama).

Written against a llama.cpp server running Qwen3.6-35B-A3B. Three findings from
probing that endpoint shape this module, and each is a deliberate choice rather
than an accident:

1. **The server's Anthropic-compatible `/v1/messages` silently drops
   `output_config.format`.** It answers 200 with prose instead of the requested
   JSON. A partial shim that fails silently is worse than no shim, so this
   provider targets `/v1/chat/completions`, where `response_format` is enforced
   by grammar-constrained decoding — a stronger guarantee than asking politely.

2. **Grammar-constrained decoding and tool calling are mutually exclusive.**
   With a `response_format` grammar active the model cannot emit `tool_calls`;
   it fills the schema with nonsense instead. Hence the two-phase completion
   below: explore with tools and no grammar, then emit the artifact under the
   grammar with no tools.

3. **Reasoning arrives in `reasoning_content`, not in the content.** It is
   mapped to a `thinking` block so the rest of the system — and the UI timeline
   — sees the same shape it gets from Anthropic.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .base import LLMRequest, LLMResponse, Sampling, Usage

log = logging.getLogger("crew.llm.openai")

REQUEST_TIMEOUT_SECONDS = 900.0

FINISH_REASON_MAP = {
    "tool_calls": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
}

class EndpointUnavailable(RuntimeError):
    """This server could not answer, but another one might.

    Kept distinct from a plain error so the pool retries only what is worth
    retrying: a 400 means the request is wrong and will be wrong everywhere.
    """


ARTIFACT_INSTRUCTION = (
    "You have finished gathering information. Now emit the required artifact as "
    "a single JSON object matching the schema. Output the object only — no "
    "prose, no code fence, no commentary."
)


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic `{name, description, input_schema}` -> OpenAI function shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in tools
    ]


def _assistant_message(content: list[dict[str, Any]]) -> dict[str, Any]:
    """Anthropic content blocks -> one OpenAI assistant message."""
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        kind = block.get("type")
        if kind == "text":
            text_parts.append(block.get("text", ""))
        elif kind == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
            )
        # thinking blocks are deliberately not replayed: local servers do not
        # accept them back and they burn context.
    entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts)}
    if tool_calls:
        entry["tool_calls"] = tool_calls
    return entry


def _user_messages(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A user turn carrying tool results -> one `tool` message per result.

    This is the one structurally important difference between the two shapes:
    Anthropic batches every result into a single user message, OpenAI wants one
    message each.
    """
    out: list[dict[str, Any]] = []
    leftover: list[str] = []
    for block in content:
        if block.get("type") == "tool_result":
            body = block.get("content")
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": body if isinstance(body, str) else json.dumps(body),
                }
            )
        elif block.get("type") == "text":
            leftover.append(block.get("text", ""))
    if leftover:
        out.append({"role": "user", "content": "\n".join(leftover)})
    return out


def _to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert the internal (Anthropic-shaped) history to OpenAI chat messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]

    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            out.append({"role": message.get("role"), "content": content})
        elif isinstance(content, list):
            if message.get("role") == "assistant":
                out.append(_assistant_message(content))
            else:
                out.extend(_user_messages(content))

    return out


def _usage_from(payload: dict[str, Any]) -> Usage:
    raw = payload.get("usage") or {}
    details = raw.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    prompt = int(raw.get("prompt_tokens") or 0)
    return Usage(
        # Cached tokens are reported inside prompt_tokens; splitting them keeps
        # the cost maths honest instead of double-counting.
        input_tokens=max(prompt - cached, 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cache_read_input_tokens=cached,
    )


class OpenAICompatibleClient:
    """Speaks `/v1/chat/completions`. Local servers usually need no API key."""

    provider = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "",
        enable_thinking: bool = True,
        max_context_tokens: int = 65_536,
        sampling: Sampling | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.enable_thinking = enable_thinking
        self.max_context_tokens = max_context_tokens
        self.sampling = sampling or Sampling()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[str]:
        """What this server actually serves.

        Two shapes in the wild, and the llama.cpp server this was written
        against returns the second: OpenAI lists `data[].id`, Ollama-style
        servers list `models[].name`. Reading only the OpenAI shape made a
        healthy server look unreachable, which is worse than not asking.
        """
        try:
            response = await self._client.get("/models")
        except httpx.TransportError as exc:
            raise EndpointUnavailable(f"{self.base_url} is unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise EndpointUnavailable(
                f"{self.base_url} returned {response.status_code} for /models"
            )
        payload = response.json()
        entries = payload.get("data") or payload.get("models") or []
        names = {
            str(entry.get("id") or entry.get("model") or entry.get("name") or "")
            for entry in entries
            if isinstance(entry, dict)
        }
        return sorted(name for name in names if name)

    # -- transport --------------------------------------------------------

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.TransportError as exc:
            # Never arrived, so retrying it elsewhere cannot duplicate an effect.
            raise EndpointUnavailable(f"{self.base_url} is unreachable: {exc}") from exc
        if response.status_code >= 500:
            # The server's problem, not the request's: worth trying elsewhere.
            raise EndpointUnavailable(
                f"{self.base_url} returned {response.status_code}: {response.text[:500]}"
            )
        if response.status_code >= 400:
            # The request itself is wrong. Sending it to another server would
            # fail identically, and would hide a bug behind a retry.
            raise RuntimeError(
                f"{self.base_url} returned {response.status_code}: {response.text[:500]}"
            )
        return response.json()

    def _base_payload(self, request: LLMRequest, messages: list[dict[str, Any]]) -> dict[str, Any]:
        # The model, not the caller, owns the context ceiling here: a local
        # 65k-context server cannot honour the 32k output budgets that are
        # reasonable against Anthropic.
        max_tokens = min(request.max_tokens, self.max_context_tokens // 4)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking and request.thinking},
        }
        payload.update(self.sampling.as_payload())
        return payload

    # -- response mapping -------------------------------------------------

    def _to_response(self, payload: dict[str, Any]) -> LLMResponse:
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        blocks: list[dict[str, Any]] = []

        reasoning = message.get("reasoning_content")
        if reasoning:
            blocks.append({"type": "thinking", "thinking": reasoning, "signature": ""})

        text = message.get("content")
        if text:
            blocks.append({"type": "text", "text": text})

        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                # Malformed arguments become an empty input; the tool layer will
                # reject it with a message the model can act on, which beats
                # crashing the run.
                log.warning("unparsable tool arguments from %s: %r", self.model, raw_arguments[:200])
                arguments = {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call.get("id", ""),
                    "name": function.get("name", ""),
                    "input": arguments,
                }
            )

        return LLMResponse(
            content=blocks,
            stop_reason=FINISH_REASON_MAP.get(choice.get("finish_reason", "stop"), "end_turn"),
            usage=_usage_from(payload),
            model=payload.get("model") or self.model,
        )

    # -- the two-phase completion ----------------------------------------

    async def complete(self, request: LLMRequest) -> LLMResponse:
        messages = _to_openai_messages(request.system, request.messages)
        payload = self._base_payload(request, messages)

        wants_artifact = request.output_format is not None
        schema = (request.output_format or {}).get("schema")

        if request.tools:
            # Phase 1 — explore. No grammar, or the model cannot call tools.
            payload["tools"] = _to_openai_tools(request.tools)
            first = self._to_response(await self._post(payload))
            if first.tool_calls:
                return first
            if not wants_artifact:
                return first
            # The model is done exploring; fall through to the constrained call,
            # carrying its closing remarks so the artifact reflects them.
            messages = list(messages)
            if first.text:
                messages.append({"role": "assistant", "content": first.text})
            messages.append({"role": "user", "content": ARTIFACT_INSTRUCTION})
            payload = self._base_payload(request, messages)
            second = await self._emit_artifact(payload, schema)
            # Bill both phases; hiding the exploration cost would misreport it.
            second.usage = second.usage + first.usage
            return second

        if wants_artifact:
            return await self._emit_artifact(payload, schema)

        return self._to_response(await self._post(payload))

    async def _emit_artifact(self, payload: dict[str, Any], schema: dict[str, Any] | None) -> LLMResponse:
        """Phase 2 — grammar-constrained emission of the artifact."""
        payload = dict(payload)
        payload.pop("tools", None)
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "artifact", "strict": True, "schema": schema},
            }
        # Reasoning before a constrained emission costs tokens and cannot change
        # the grammar-forced output, so it is switched off for this call.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        return self._to_response(await self._post(payload))
