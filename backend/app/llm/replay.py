"""Replay provider.

Re-executes a recorded run's orchestration using the artifacts that run
actually produced, calling no model. That turns every real run into a
regression fixture: change the state machine, replay a run that cost real
tokens, and see whether the orchestration still reaches the same end — for
free, offline, and against genuine model output rather than hand-written
doubles.

It answers by artifact schema rather than by call order, so it keeps working
when a phase gains or loses a tool call.
"""

from __future__ import annotations

import json
from typing import Any

from ..store.database import Database
from .base import LLMRequest, LLMResponse, Usage

SCHEMA_BY_KIND = {
    "intake": "IntakeBrief",
    "spec": "Spec",
    "plan": "Plan",
    "changeset": "ChangeSet",
    "qa_report": "QAReport",
    "docs_bundle": "DocsBundle",
}


class ReplayExhausted(RuntimeError):
    """The orchestration asked for something the recorded run never produced."""


class ReplayLLMClient:
    provider = "replay"

    def __init__(self, db: Database, run_id: str) -> None:
        self.run_id = run_id
        self.calls: list[LLMRequest] = []
        # Artifacts are stored per iteration; replay them in the order they were
        # produced, so a recorded repair loop replays as a repair loop.
        self._queues: dict[str, list[dict[str, Any]]] = {}
        for artifact in sorted(db.get_artifacts(run_id), key=lambda a: (a["created_at"], a["iteration"])):
            title = SCHEMA_BY_KIND.get(artifact["kind"])
            if title:
                self._queues.setdefault(title, []).append(artifact["payload"])

    @property
    def recorded(self) -> dict[str, int]:
        return {title: len(queue) for title, queue in self._queues.items()}

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        title = (request.output_format or {}).get("schema", {}).get("title", "")
        queue = self._queues.get(title)
        if not queue:
            raise ReplayExhausted(
                f"run {self.run_id} recorded no further {title or 'artifact'} — "
                "the orchestration asked for something the original run never produced"
            )
        # Hold the last one: a replayed repair loop that runs one iteration
        # longer reuses the final recorded verdict instead of crashing.
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return LLMResponse(
            content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            stop_reason="end_turn",
            usage=Usage(),
            model="replay",
        )
