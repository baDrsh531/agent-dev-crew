"""Roles, run phases and statuses — the vocabulary the whole system shares."""

from __future__ import annotations

from enum import Enum


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    TRANSLATOR = "translator"
    ANALYST = "analyst"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    QA = "qa"
    DOCUMENTER = "documenter"

    @property
    def label(self) -> str:
        return {
            AgentRole.ORCHESTRATOR: "Project Manager",
            AgentRole.TRANSLATOR: "Intake",
            AgentRole.ANALYST: "Business Analyst",
            AgentRole.ARCHITECT: "Software Architect",
            AgentRole.DEVELOPER: "Developer",
            AgentRole.QA: "QA Engineer",
            AgentRole.DOCUMENTER: "Documentation Writer",
        }[self]


class RunPhase(str, Enum):
    """Nodes of the orchestration graph. Transitions are decided in code."""

    INTAKE = "intake"
    INTAKE_APPROVAL = "intake_approval"
    ANALYZE = "analyze"
    DESIGN = "design"
    PLAN_APPROVAL = "plan_approval"
    IMPLEMENT = "implement"
    REVIEW = "review"
    FIX = "fix"
    DOCUMENT = "document"
    DONE = "done"
    ESCALATED = "escalated"
    FAILED = "failed"


TERMINAL_PHASES = frozenset({RunPhase.DONE, RunPhase.ESCALATED, RunPhase.FAILED})


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    SUCCEEDED = "succeeded"
    ESCALATED = "escalated"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.ESCALATED, RunStatus.FAILED, RunStatus.CANCELLED}
)
