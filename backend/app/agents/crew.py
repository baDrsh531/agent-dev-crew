"""The crew: one Agent instance per role, wired to its schema and tool set."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from ..config import Settings, get_settings
from ..domain.artifacts import (
    ChangeSet,
    DocsBundle,
    IntakeBrief,
    Plan,
    QAReport,
    Spec,
    output_format_for,
)
from ..domain.roles import AgentRole
from ..llm.factory import model_for
from ..tools.registry import tools_for_role
from . import prompts
from .base import Agent


@dataclass(frozen=True, slots=True)
class RoleSetup:
    artifact: type[BaseModel]
    max_tokens: int
    effort: str


# Effort is per role, not global: design and implementation are the
# intelligence-sensitive steps; documentation is largely mechanical.
ROLE_SETUP: dict[AgentRole, RoleSetup] = {
    AgentRole.TRANSLATOR: RoleSetup(IntakeBrief, 8_000, "high"),
    AgentRole.ANALYST: RoleSetup(Spec, 8_000, "high"),
    AgentRole.ARCHITECT: RoleSetup(Plan, 16_000, "xhigh"),
    AgentRole.DEVELOPER: RoleSetup(ChangeSet, 32_000, "xhigh"),
    AgentRole.QA: RoleSetup(QAReport, 16_000, "high"),
    AgentRole.DOCUMENTER: RoleSetup(DocsBundle, 12_000, "medium"),
}


def build_agent(
    role: AgentRole, settings: Settings | None = None, repo_map: str = ""
) -> Agent:
    settings = settings or get_settings()
    setup = ROLE_SETUP[role]
    return Agent(
        role=role,
        system_prompt=prompts.system_prompt(role.value, repo_map),
        output_model=setup.artifact,
        output_format=output_format_for(setup.artifact),
        tools=tools_for_role(role),
        model=model_for(role, settings),
        max_tokens=setup.max_tokens,
        effort=setup.effort,
    )


def build_crew(
    settings: Settings | None = None, repo_map: str = ""
) -> dict[AgentRole, Agent]:
    settings = settings or get_settings()
    return {role: build_agent(role, settings, repo_map) for role in ROLE_SETUP}
