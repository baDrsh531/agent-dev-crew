"""Tool plumbing: definitions, execution context, and the permission matrix.

Two ideas carry this module. First, a tool is data (name + schema + handler),
so the same object can be serialised to the API and dispatched locally.
Second, capability is per role, not global: the analyst physically cannot
write a file, because `write_file` is not in its tool list.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..domain.roles import AgentRole
from ..workspace.sandbox import Sandbox


@dataclass(slots=True)
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def error(cls, message: str, **metadata: Any) -> "ToolResult":
        return cls(content=message, is_error=True, metadata=metadata)


ApprovalFn = Callable[[str, str, dict[str, Any]], Awaitable[tuple[bool, str]]]
"""(tool_name, human_summary, tool_input) -> (approved, reason)."""


@dataclass(slots=True)
class ToolContext:
    sandbox: Sandbox
    run_id: str
    role: AgentRole
    request_approval: ApprovalFn
    approval_required: bool = True

    async def confirm(self, tool_name: str, summary: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        if not self.approval_required:
            return True, "auto-approved"
        return await self.request_approval(tool_name, summary, tool_input)


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    mutating: bool = False
    """Mutating tools change the workspace and go through the approval gate."""
    reversible: bool = True
    """Whether a `git reset` to the run's base commit undoes it.

    True for anything confined to the working tree. False for commands, whose
    effects — an installed package, a network call — outlive the branch. This
    is what the middle autonomy setting keys on, so it is a property of the
    tool rather than a judgement made at the call site.
    """

    def to_api_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def obj_schema(
    properties: dict[str, dict[str, Any]], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
    }


# --------------------------------------------------------------------------
# Least privilege: which role may call which tool
# --------------------------------------------------------------------------

ROLE_TOOLS: dict[AgentRole, frozenset[str]] = {
    # Talks to the human. Reads just enough to ground their words in the code.
    AgentRole.TRANSLATOR: frozenset({"read_file", "list_files", "search_code"}),
    # Reads the request and the codebase. Cannot touch anything.
    AgentRole.ANALYST: frozenset({"read_file", "list_files", "search_code"}),
    # Decides the design from evidence. Still read-only — plans are not edits.
    AgentRole.ARCHITECT: frozenset({"read_file", "list_files", "search_code"}),
    # The only role that may write, install and commit.
    AgentRole.DEVELOPER: frozenset(
        {
            "read_file", "list_files", "search_code",
            "write_file", "edit_file", "delete_file",
            "run_command", "run_tests", "git_commit",
        }
    ),
    # Verifies. May run the suite, may not fix what it finds.
    AgentRole.QA: frozenset(
        {"read_file", "list_files", "search_code", "run_tests", "git_diff"}
    ),
    # Writes prose only, and only into documentation paths (enforced in fs.py).
    AgentRole.DOCUMENTER: frozenset(
        {"read_file", "list_files", "search_code", "git_diff", "write_doc"}
    ),
    # Coordinates; the state machine does the work, so it needs nothing.
    AgentRole.ORCHESTRATOR: frozenset(),
}


def tools_for(role: AgentRole, registry: dict[str, Tool]) -> list[Tool]:
    allowed = ROLE_TOOLS.get(role, frozenset())
    return [registry[name] for name in sorted(allowed) if name in registry]


def needs_approval(mode: str, tool: Tool) -> bool:
    """Whether this tool call stops for a human under this autonomy setting.

    One function, so the policy cannot drift between the engine, the API and
    whatever the UI claims it is doing.
    """
    if mode == "auto" or not tool.mutating:
        return False
    if mode == "risky":
        return not tool.reversible
    return True  # "ask"
