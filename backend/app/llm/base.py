"""Provider-neutral shapes for a model call.

Agent code never touches the Anthropic SDK directly. It builds a `LLMRequest`
and receives an `LLMResponse` whose content blocks are plain dicts, which makes
the whole pipeline trivially serialisable, replayable and testable against the
fake provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# USD per million tokens, (input, output). Cache reads bill at ~0.1x input,
# cache writes at ~1.25x. Source: Anthropic pricing, 2026-06.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "fake": (0.0, 0.0),
}
# A model with no entry is self-hosted (a local llama.cpp / vLLM server) or the
# fake provider: the marginal cost of a token is zero. Charging it at Opus rates
# would put an invented number in the UI, which is worse than reporting nothing.
UNPRICED = (0.0, 0.0)


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
        )

    def cost_usd(self, model: str) -> float:
        price_in, price_out = PRICING.get(model, UNPRICED)
        return (
            self.input_tokens * price_in
            + self.cache_creation_input_tokens * price_in * 1.25
            + self.cache_read_input_tokens * price_in * 0.10
            + self.output_tokens * price_out
        ) / 1_000_000

    def as_dict(self, model: str = "") -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd(model), 6) if model else 0.0,
        }


@dataclass(slots=True)
class Sampling:
    """Decoding parameters. `None` means "do not send it, use the server's own".

    Left unset, a local server applies its own defaults — which are random, and
    which made three identical requests return three different plans. Pinning
    `temperature=0` made them byte-identical. Anthropic models reject these
    parameters, so they are only ever sent to OpenAI-compatible providers.
    """

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    seed: int | None = None

    @property
    def is_greedy(self) -> bool:
        return self.temperature == 0

    def as_payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in (
                ("temperature", self.temperature), ("top_p", self.top_p),
                ("top_k", self.top_k), ("seed", self.seed),
            )
            if value is not None
        }


@dataclass(slots=True)
class LLMRequest:
    model: str
    system: str
    messages: list[dict[str, Any]]
    max_tokens: int = 16_000
    tools: list[dict[str, Any]] = field(default_factory=list)
    output_format: dict[str, Any] | None = None
    effort: str = "high"
    thinking: bool = True


@dataclass(slots=True)
class LLMResponse:
    content: list[dict[str, Any]]
    stop_reason: str
    usage: Usage
    model: str

    @property
    def text(self) -> str:
        return "\n".join(
            block.get("text", "") for block in self.content if block.get("type") == "text"
        ).strip()

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return [block for block in self.content if block.get("type") == "tool_use"]

    @property
    def thinking_text(self) -> str:
        return "\n".join(
            block.get("thinking", "")
            for block in self.content
            if block.get("type") == "thinking"
        ).strip()

    @property
    def refused(self) -> bool:
        return self.stop_reason == "refusal"


class LLMClient(Protocol):
    provider: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...
