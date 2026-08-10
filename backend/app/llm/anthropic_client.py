"""Anthropic provider.

Per-model capability gating lives here rather than at the call sites: the
agents ask for "adaptive thinking at high effort" and this module quietly drops
what a given model does not accept, instead of returning a 400 mid-run.
"""

from __future__ import annotations

from typing import Any

from .base import LLMRequest, LLMResponse, Usage

# Models that accept `thinking: {"type": "adaptive"}` and `output_config.effort`.
MODERN_MODELS = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5")
# Above this, a non-streaming request risks an HTTP timeout.
STREAM_THRESHOLD_TOKENS = 16_000


def _supports_adaptive(model: str) -> bool:
    return model.startswith(MODERN_MODELS) or model.startswith("claude-opus-4-6") \
        or model.startswith("claude-sonnet-4-6")


def _supports_effort(model: str) -> bool:
    return _supports_adaptive(model)


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Normalise an SDK content block into a plain, serialisable dict."""
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    if isinstance(block, dict):
        return block
    return {"type": getattr(block, "type", "unknown"), "raw": str(block)}


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str) -> None:
        from anthropic import AsyncAnthropic  # imported lazily: optional dependency

        self._client = AsyncAnthropic(api_key=api_key)

    def _build_params(self, request: LLMRequest) -> dict[str, Any]:
        # The system prompt is the stable prefix of every turn, so it carries the
        # cache breakpoint. Tools render before it and are cached with it.
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": request.messages,
        }
        if request.tools:
            params["tools"] = request.tools

        output_config: dict[str, Any] = {}
        if request.output_format is not None:
            output_config["format"] = request.output_format
        if _supports_effort(request.model):
            output_config["effort"] = request.effort
        if output_config:
            params["output_config"] = output_config

        if request.thinking and _supports_adaptive(request.model):
            # "summarized" so the UI can show what the agent was reasoning about;
            # the default omits the text entirely.
            params["thinking"] = {"type": "adaptive", "display": "summarized"}
        return params

    async def complete(self, request: LLMRequest) -> LLMResponse:
        params = self._build_params(request)

        if request.max_tokens > STREAM_THRESHOLD_TOKENS:
            async with self._client.messages.stream(**params) as stream:
                message = await stream.get_final_message()
        else:
            message = await self._client.messages.create(**params)

        raw_usage = message.usage
        usage = Usage(
            input_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
            output_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(raw_usage, "cache_creation_input_tokens", 0) or 0,
        )
        return LLMResponse(
            content=[_block_to_dict(block) for block in message.content],
            stop_reason=message.stop_reason or "end_turn",
            usage=usage,
            model=message.model,
        )
