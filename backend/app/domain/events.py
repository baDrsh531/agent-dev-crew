"""The event log.

Everything the crew does is appended here before it is acted on. Two things
fall out of that for free: the UI is a projection of the stream, and a crashed
run can be rebuilt by replaying it. Events are immutable and ordered by `seq`
within a run.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .roles import AgentRole, RunPhase


class EventType(str, Enum):
    RUN_CREATED = "run.created"
    RUN_STATUS_CHANGED = "run.status_changed"
    RUN_FINISHED = "run.finished"

    PHASE_STARTED = "phase.started"
    PHASE_FINISHED = "phase.finished"

    AGENT_STARTED = "agent.started"
    AGENT_MESSAGE = "agent.message"
    AGENT_FINISHED = "agent.finished"
    AGENT_FAILED = "agent.failed"

    TOOL_REQUESTED = "tool.requested"
    TOOL_EXECUTED = "tool.executed"
    TOOL_DENIED = "tool.denied"

    ARTIFACT_PRODUCED = "artifact.produced"
    DECISION_RECORDED = "decision.recorded"

    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"

    BUDGET_UPDATED = "budget.updated"
    LIMIT_REACHED = "limit.reached"

    HANDOFF = "handoff"
    LOG = "log"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Event(BaseModel):
    """One immutable fact about a run."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    seq: int = 0  # assigned by the store on append
    type: EventType
    at: datetime = Field(default_factory=_now)
    phase: RunPhase | None = None
    role: AgentRole | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "seq": self.seq,
            "type": self.type.value,
            "at": self.at.isoformat(),
            "phase": self.phase.value if self.phase else None,
            "role": self.role.value if self.role else None,
            "payload": self.payload,
        }


def event(
    run_id: str,
    type: EventType,
    payload: dict[str, Any] | None = None,
    *,
    phase: RunPhase | None = None,
    role: AgentRole | None = None,
) -> Event:
    """Terse constructor.

    `payload` is an explicit dict rather than **kwargs so that a payload key
    named "phase" or "role" cannot collide with the parameters.
    """
    return Event(run_id=run_id, type=type, phase=phase, role=role, payload=payload or {})
