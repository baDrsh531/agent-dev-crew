"""The agent loop.

One class runs every role. What differs between an analyst and a developer is
data — a system prompt, a tool list, an output schema — not control flow. The
loop itself is deliberately boring: call the model, execute whatever tools it
asked for, feed the results back, stop when it produces its artifact or when a
ceiling is hit.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ..domain.events import EventType
from ..domain.roles import AgentRole
from ..llm.base import LLMClient, LLMRequest, LLMResponse, Usage
from ..tools.base import Tool, ToolContext, ToolResult, needs_approval
from ..workspace.sandbox import Sandbox

T = TypeVar("T", bound=BaseModel)

MAX_SCHEMA_REPAIR_ATTEMPTS = 2

EmitFn = Callable[[EventType, dict[str, Any]], Awaitable[None]]
ApprovalFn = Callable[[str, str, dict[str, Any]], Awaitable[tuple[bool, str]]]


class AgentError(RuntimeError):
    """The agent could not produce a valid artifact within its limits."""


class BudgetExceeded(AgentError):
    pass


@dataclass(slots=True)
class Budget:
    """Ceilings, not hints. Crossing one stops the run."""

    max_tokens: int
    max_tool_calls: int
    tokens_used: int = 0
    tool_calls_used: int = 0
    cost_usd: float = 0.0

    def charge(self, usage: Usage, model: str) -> None:
        self.tokens_used += usage.total_tokens
        self.cost_usd += usage.cost_usd(model)

    def check_tokens(self) -> None:
        if self.tokens_used >= self.max_tokens:
            raise BudgetExceeded(
                f"token budget exhausted ({self.tokens_used}/{self.max_tokens})"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "max_tokens": self.max_tokens,
            "tool_calls_used": self.tool_calls_used,
            "max_tool_calls": self.max_tool_calls,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass(slots=True)
class AgentContext:
    run_id: str
    sandbox: Sandbox
    llm: LLMClient
    budget: Budget
    emit: EmitFn
    request_approval: ApprovalFn
    approval_mode: str = "ask"


@dataclass(slots=True)
class AgentOutcome(Generic[T]):
    artifact: T
    usage: Usage
    model: str
    tool_calls: int
    transcript: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Agent(Generic[T]):
    role: AgentRole
    system_prompt: str
    output_model: type[T]
    output_format: dict[str, Any]
    tools: list[Tool]
    model: str
    max_tokens: int = 16_000
    effort: str = "high"

    # -- helpers ---------------------------------------------------------

    def _tool_by_name(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)

    async def _execute_tool(
        self, call: dict[str, Any], ctx: AgentContext
    ) -> dict[str, Any]:
        name = call.get("name", "")
        args = call.get("input") or {}
        tool = self._tool_by_name(name)

        await ctx.emit(
            EventType.TOOL_REQUESTED,
            {"role": self.role.value, "tool": name, "input": args},
        )

        if tool is None:
            # Not an exception: tell the model, let it correct itself.
            result = ToolResult.error(
                f"{name!r} is not available to the {self.role.label}. Available "
                f"tools: {', '.join(t.name for t in self.tools) or 'none'}."
            )
        else:
            tool_ctx = ToolContext(
                sandbox=ctx.sandbox,
                run_id=ctx.run_id,
                role=self.role,
                request_approval=ctx.request_approval,
                approval_required=needs_approval(ctx.approval_mode, tool),
            )
            try:
                result = await tool.handler(tool_ctx, args)
            except Exception as exc:  # a tool bug must not kill the run
                result = ToolResult.error(f"{type(exc).__name__}: {exc}")

        ctx.budget.tool_calls_used += 1
        await ctx.emit(
            EventType.TOOL_DENIED if result.is_error else EventType.TOOL_EXECUTED,
            {
                "role": self.role.value,
                "tool": name,
                "input": args,
                "is_error": result.is_error,
                "output": result.content[:4000],
                "metadata": result.metadata,
            },
        )
        return {
            "type": "tool_result",
            "tool_use_id": call.get("id", ""),
            "content": result.content or "(no output)",
            "is_error": result.is_error,
        }

    def _parse(self, response: LLMResponse) -> T:
        text = response.text
        if not text:
            raise ValidationError.from_exception_data(self.output_model.__name__, [])
        # Structured outputs guarantee bare JSON, but a fenced block is cheap to survive.
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return self.output_model.model_validate_json(cleaned)

    # -- the loop --------------------------------------------------------

    async def run(self, task: str, ctx: AgentContext) -> AgentOutcome[T]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        total_usage = Usage()
        tool_calls = 0
        repairs = 0

        await ctx.emit(
            EventType.AGENT_STARTED,
            {"role": self.role.value, "label": self.role.label, "model": self.model},
        )

        while True:
            ctx.budget.check_tokens()
            if tool_calls > ctx.budget.max_tool_calls:
                raise BudgetExceeded(
                    f"{self.role.label} exceeded {ctx.budget.max_tool_calls} tool calls"
                )

            response = await ctx.llm.complete(
                LLMRequest(
                    model=self.model,
                    system=self.system_prompt,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    tools=[t.to_api_schema() for t in self.tools],
                    output_format=self.output_format,
                    effort=self.effort,
                )
            )
            total_usage = total_usage + response.usage
            ctx.budget.charge(response.usage, self.model)
            await ctx.emit(EventType.BUDGET_UPDATED, ctx.budget.as_dict())

            if response.refused:
                raise AgentError(
                    f"{self.role.label}: the model declined this request "
                    "(stop_reason=refusal)."
                )

            if response.thinking_text:
                await ctx.emit(
                    EventType.AGENT_MESSAGE,
                    {"role": self.role.value, "kind": "thinking", "text": response.thinking_text},
                )
            if response.text and response.tool_calls:
                await ctx.emit(
                    EventType.AGENT_MESSAGE,
                    {"role": self.role.value, "kind": "narration", "text": response.text},
                )

            if response.tool_calls:
                messages.append({"role": "assistant", "content": response.content})
                # All results for one assistant turn go back in a single user
                # message — splitting them trains the model out of parallel calls.
                results = [await self._execute_tool(c, ctx) for c in response.tool_calls]
                tool_calls += len(results)
                messages.append({"role": "user", "content": results})
                continue

            try:
                artifact = self._parse(response)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                repairs += 1
                if repairs >= MAX_SCHEMA_REPAIR_ATTEMPTS:
                    raise AgentError(
                        f"{self.role.label} produced an artifact that does not match "
                        f"the {self.output_model.__name__} schema: {exc}"
                    ) from exc
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your last message did not validate against the required "
                            f"schema.\n\n{exc}\n\nReturn the corrected object only."
                        ),
                    }
                )
                continue

            await ctx.emit(
                EventType.AGENT_FINISHED,
                {
                    "role": self.role.value,
                    "tool_calls": tool_calls,
                    "usage": total_usage.as_dict(self.model),
                },
            )
            return AgentOutcome(
                artifact=artifact,
                usage=total_usage,
                model=self.model,
                tool_calls=tool_calls,
                transcript=messages,
            )
