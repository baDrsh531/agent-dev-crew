"""The agent loop: least privilege, approval gates, and bounded retries.

The permission matrix is only a claim until a test proves that an agent
*calling* a forbidden tool changes nothing on disk.
"""

from __future__ import annotations

import pytest

from app.agents.base import Agent, AgentContext, AgentError, Budget, BudgetExceeded
from app.agents.crew import build_agent
from app.domain.artifacts import Spec, output_format_for
from app.domain.roles import AgentRole
from app.llm.base import LLMRequest, LLMResponse, Usage
from app.tools.registry import tools_for_role
from conftest import make_spec

pytestmark = pytest.mark.asyncio


class SequenceClient:
    """Replays a fixed list of responses, then repeats the last one."""

    provider = "fake"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def tool_use(name: str, args: dict, call_id: str = "t1") -> LLMResponse:
    return LLMResponse(
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=10),
        model="fake",
    )


def final(text: str) -> LLMResponse:
    return LLMResponse(
        content=[{"type": "text", "text": text}],
        stop_reason="end_turn",
        usage=Usage(input_tokens=10, output_tokens=10),
        model="fake",
    )


def make_context(sandbox, client, *, approvals=None, approval_mode="ask", max_tool_calls=10):
    recorded: list[tuple[str, str, dict]] = []

    async def request_approval(tool, summary, tool_input):
        recorded.append((tool, summary, tool_input))
        return (approvals or {}).get(tool, (True, "auto"))

    ctx = AgentContext(
        run_id="run-1",
        sandbox=sandbox,
        llm=client,
        budget=Budget(max_tokens=1_000_000, max_tool_calls=max_tool_calls),
        emit=_noop_emit,
        request_approval=request_approval,
        approval_mode=approval_mode,
    )
    return ctx, recorded


async def _noop_emit(event_type, payload) -> None:
    return None


def analyst_agent() -> Agent:
    return Agent(
        role=AgentRole.ANALYST,
        system_prompt="test",
        output_model=Spec,
        output_format=output_format_for(Spec),
        tools=tools_for_role(AgentRole.ANALYST),
        model="fake",
    )


# -- least privilege ---------------------------------------------------------


async def test_analyst_cannot_write_and_the_file_is_not_created(sandbox):
    client = SequenceClient(
        [
            tool_use("write_file", {"path": "app/hacked.py", "content": "x"}),
            final(make_spec().model_dump_json()),
        ]
    )
    ctx, _ = make_context(sandbox, client)

    outcome = await analyst_agent().run("spec this", ctx)

    assert outcome.artifact.summary  # the agent still finished
    assert not (sandbox.root / "app" / "hacked.py").exists()
    # The refusal is fed back as a tool_result so the model can correct itself.
    tool_results = [
        block
        for message in outcome.transcript
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert tool_results and tool_results[0]["is_error"]
    assert "not available" in tool_results[0]["content"]


async def test_documenter_cannot_write_source_files(sandbox):
    documenter = build_agent(AgentRole.DOCUMENTER)
    tool = next(t for t in documenter.tools if t.name == "write_doc")
    ctx, _ = make_context(sandbox, SequenceClient([final("{}")]))

    from app.tools.base import ToolContext

    tool_ctx = ToolContext(
        sandbox=sandbox, run_id="r", role=AgentRole.DOCUMENTER,
        request_approval=ctx.request_approval, approval_required=False,
    )
    result = await tool.handler(tool_ctx, {"path": "app/main.py", "content": "evil"})

    assert result.is_error and "not a documentation path" in result.content
    assert sandbox.read_text("app/main.py") == "def hello():\n    return 'hi'\n"


async def test_documenter_may_write_markdown(sandbox):
    documenter = build_agent(AgentRole.DOCUMENTER)
    tool = next(t for t in documenter.tools if t.name == "write_doc")

    from app.tools.base import ToolContext

    tool_ctx = ToolContext(
        sandbox=sandbox, run_id="r", role=AgentRole.DOCUMENTER,
        request_approval=_always_approve, approval_required=False,
    )
    result = await tool.handler(tool_ctx, {"path": "docs/auth.md", "content": "# Auth"})

    assert not result.is_error
    assert sandbox.read_text("docs/auth.md") == "# Auth"


async def _always_approve(tool, summary, tool_input):
    return True, "ok"


# -- approval gates ----------------------------------------------------------


async def test_write_asks_for_approval_and_a_denial_prevents_the_write(sandbox):
    client = SequenceClient(
        [
            tool_use("write_file", {"path": "app/new.py", "content": "print(1)"}),
            final(make_spec().model_dump_json()),
        ]
    )
    developer = Agent(
        role=AgentRole.DEVELOPER, system_prompt="test", output_model=Spec,
        output_format=output_format_for(Spec), tools=tools_for_role(AgentRole.DEVELOPER),
        model="fake",
    )
    ctx, recorded = make_context(sandbox, client, approvals={"write_file": (False, "not yet")})

    await developer.run("do it", ctx)

    assert recorded and recorded[0][0] == "write_file"
    assert not (sandbox.root / "app" / "new.py").exists()


async def test_auto_mode_skips_the_gate(sandbox):
    client = SequenceClient(
        [
            tool_use("write_file", {"path": "app/new.py", "content": "print(1)"}),
            final(make_spec().model_dump_json()),
        ]
    )
    developer = Agent(
        role=AgentRole.DEVELOPER, system_prompt="test", output_model=Spec,
        output_format=output_format_for(Spec), tools=tools_for_role(AgentRole.DEVELOPER),
        model="fake",
    )
    ctx, recorded = make_context(sandbox, client, approval_mode="auto")

    await developer.run("do it", ctx)

    assert recorded == []
    assert sandbox.read_text("app/new.py") == "print(1)"


# -- the autonomy setting ----------------------------------------------------


async def test_the_middle_setting_lets_a_reversible_write_through(sandbox):
    """Editing a file on the run's own branch is undone by a git reset, so it
    is not what "ask me when it cannot be undone" means."""
    client = SequenceClient([
        tool_use("write_file", {"path": "app/new.py", "content": "print(1)"}),
        final(make_spec().model_dump_json()),
    ])
    developer = Agent(
        role=AgentRole.DEVELOPER, system_prompt="test", output_model=Spec,
        output_format=output_format_for(Spec), tools=tools_for_role(AgentRole.DEVELOPER),
        model="fake",
    )
    ctx, recorded = make_context(sandbox, client, approval_mode="risky")

    await developer.run("do it", ctx)

    assert recorded == [], "a reversible write must not interrupt at this setting"
    assert sandbox.read_text("app/new.py") == "print(1)"


async def test_the_middle_setting_still_stops_for_a_command(sandbox):
    """An installed package outlives the branch, so it is asked about."""
    client = SequenceClient([
        tool_use("run_command", {"command": "pip install requests"}),
        final(make_spec().model_dump_json()),
    ])
    developer = Agent(
        role=AgentRole.DEVELOPER, system_prompt="test", output_model=Spec,
        output_format=output_format_for(Spec), tools=tools_for_role(AgentRole.DEVELOPER),
        model="fake",
    )
    ctx, recorded = make_context(
        sandbox, client, approval_mode="risky", approvals={"run_command": (False, "no")}
    )

    await developer.run("do it", ctx)

    assert [call[0] for call in recorded] == ["run_command"]


def test_the_policy_lives_in_one_place() -> None:
    """Engine, API and UI must not each decide this differently."""
    from app.tools.base import needs_approval
    from app.tools.registry import REGISTRY

    write, command = REGISTRY["write_file"], REGISTRY["run_command"]

    assert needs_approval("ask", write) and needs_approval("ask", command)
    assert not needs_approval("risky", write) and needs_approval("risky", command)
    assert not needs_approval("auto", write) and not needs_approval("auto", command)
    assert not needs_approval("ask", REGISTRY["read_file"]), "reads never ask"


# -- bounds ------------------------------------------------------------------


async def test_tool_call_ceiling_stops_a_looping_agent(sandbox):
    client = SequenceClient([tool_use("list_files", {})])  # never stops asking
    ctx, _ = make_context(sandbox, client, max_tool_calls=3)

    with pytest.raises(BudgetExceeded):
        await analyst_agent().run("loop forever", ctx)


async def test_token_ceiling_stops_the_agent(sandbox):
    client = SequenceClient([tool_use("list_files", {})])
    ctx, _ = make_context(sandbox, client)
    ctx.budget = Budget(max_tokens=15, max_tool_calls=100)

    with pytest.raises(BudgetExceeded):
        await analyst_agent().run("burn tokens", ctx)


# -- schema repair -----------------------------------------------------------


async def test_invalid_artifact_gets_one_repair_attempt(sandbox):
    client = SequenceClient([final("not json at all"), final(make_spec().model_dump_json())])
    ctx, _ = make_context(sandbox, client)

    outcome = await analyst_agent().run("spec this", ctx)

    assert outcome.artifact.summary == "Protect write routes with JWT."
    assert len(client.calls) == 2  # one repair round trip, not an infinite loop


async def test_persistently_invalid_artifact_fails_loudly(sandbox):
    client = SequenceClient([final("still not json")])
    ctx, _ = make_context(sandbox, client)

    with pytest.raises(AgentError, match="does not match"):
        await analyst_agent().run("spec this", ctx)


async def test_a_refusal_is_surfaced_not_swallowed(sandbox):
    client = SequenceClient(
        [LLMResponse(content=[], stop_reason="refusal", usage=Usage(), model="fake")]
    )
    ctx, _ = make_context(sandbox, client)

    with pytest.raises(AgentError, match="declined"):
        await analyst_agent().run("spec this", ctx)


# -- request shape -----------------------------------------------------------


async def test_agent_sends_only_its_own_tools(sandbox):
    client = SequenceClient([final(make_spec().model_dump_json())])
    ctx, _ = make_context(sandbox, client)

    await analyst_agent().run("spec this", ctx)

    sent = {tool["name"] for tool in client.calls[0].tools}
    assert sent == {"read_file", "list_files", "search_code"}
    assert "write_file" not in sent


async def test_agent_requests_its_artifact_schema(sandbox):
    client = SequenceClient([final(make_spec().model_dump_json())])
    ctx, _ = make_context(sandbox, client)

    await analyst_agent().run("spec this", ctx)

    schema = client.calls[0].output_format["schema"]
    assert schema["title"] == "Spec"
    assert schema["additionalProperties"] is False
