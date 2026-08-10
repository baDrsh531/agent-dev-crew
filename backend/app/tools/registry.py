"""The single place tools are assembled and looked up."""

from __future__ import annotations

from ..domain.roles import AgentRole
from .base import ROLE_TOOLS, Tool, tools_for
from .fs import FS_TOOLS
from .shell import SHELL_TOOLS
from .vcs import VCS_TOOLS

ALL_TOOLS: list[Tool] = [*FS_TOOLS, *SHELL_TOOLS, *VCS_TOOLS]
REGISTRY: dict[str, Tool] = {tool.name: tool for tool in ALL_TOOLS}


def get_tool(name: str) -> Tool | None:
    return REGISTRY.get(name)


def tools_for_role(role: AgentRole) -> list[Tool]:
    return tools_for(role, REGISTRY)


def permission_matrix() -> dict[str, dict[str, str]]:
    """Role x tool capability table — surfaced in the UI as a security story."""
    matrix: dict[str, dict[str, str]] = {}
    for role in AgentRole:
        allowed = ROLE_TOOLS.get(role, frozenset())
        matrix[role.value] = {
            tool.name: (
                "approval" if tool.name in allowed and tool.mutating
                else "allowed" if tool.name in allowed
                else "denied"
            )
            for tool in ALL_TOOLS
        }
    return matrix


def _validate() -> None:
    """Fail at import time if a role references a tool that does not exist."""
    known = set(REGISTRY)
    for role, names in ROLE_TOOLS.items():
        unknown = names - known
        if unknown:
            raise RuntimeError(f"{role.value} references unknown tools: {sorted(unknown)}")


_validate()
