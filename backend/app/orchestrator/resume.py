"""Reconstructing a run from what was persisted.

Resume is **phase-level**, not turn-level. A run interrupted mid-agent restarts
that agent from the top rather than trying to rebuild a half-finished
conversation — the artifacts are the honest record of what is genuinely done,
and an agent turn is cheap to redo compared to the risk of resuming from a
state nobody can verify.

The resume point is therefore *derived from the artifacts*, never stored as a
separate cursor that could disagree with them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from ..domain.artifacts import ChangeSet, DocsBundle, Plan, QAReport, Spec
from ..domain.events import EventType
from ..domain.roles import RunPhase
from ..store.database import Database


def _parse(model: type[BaseModel], payload: dict[str, Any] | None) -> Any:
    if payload is None:
        return None
    try:
        return model.model_validate(payload)
    except ValidationError:
        # A stored artifact that no longer matches its schema (the models moved
        # on) is treated as absent: redo the phase rather than resume on a shape
        # the rest of the pipeline cannot consume.
        return None


@dataclass(slots=True)
class ResumeState:
    spec: Spec | None = None
    plan: Plan | None = None
    changeset: ChangeSet | None = None
    report: QAReport | None = None
    docs: DocsBundle | None = None
    qa_iterations: int = 0
    branch: str = ""
    base_commit: str = ""
    plan_approved: bool = False

    @property
    def is_fresh(self) -> bool:
        return self.spec is None

    @property
    def next_phase(self) -> RunPhase:
        """Where the run picks up. Derived, so it cannot drift from the record."""
        if self.spec is None:
            return RunPhase.ANALYZE
        if self.plan is None:
            return RunPhase.DESIGN
        if not self.plan_approved:
            return RunPhase.PLAN_APPROVAL
        if self.changeset is None:
            return RunPhase.IMPLEMENT
        if self.report is None:
            return RunPhase.REVIEW
        if self.docs is None:
            return RunPhase.DOCUMENT
        return RunPhase.DONE

    @classmethod
    def load(cls, db: Database, run_id: str) -> "ResumeState":
        run = db.get_run(run_id) or {}
        latest: dict[str, dict[str, Any]] = {}
        highest_iteration = 0
        for artifact in db.get_artifacts(run_id):
            # Artifacts are stored per iteration; the last one wins.
            kind, iteration = artifact["kind"], artifact["iteration"]
            highest_iteration = max(highest_iteration, iteration)
            previous = latest.get(kind)
            if previous is None or iteration >= previous["iteration"]:
                latest[kind] = artifact

        def payload(kind: str) -> dict[str, Any] | None:
            entry = latest.get(kind)
            return entry["payload"] if entry else None

        approved = any(
            event["type"] == EventType.APPROVAL_RESOLVED.value
            and event["payload"].get("approved")
            and event["payload"].get("tool") in (None, "plan")
            for event in db.get_events(run_id)
        )
        # An auto-mode run never records a plan approval, so treat having gone
        # past DESIGN as approval: the presence of a changeset proves it.
        if payload("changeset") is not None:
            approved = True

        return cls(
            spec=_parse(Spec, payload("spec")),
            plan=_parse(Plan, payload("plan")),
            changeset=_parse(ChangeSet, payload("changeset")),
            report=_parse(QAReport, payload("qa_report")),
            docs=_parse(DocsBundle, payload("docs_bundle")),
            qa_iterations=int(run.get("qa_iterations") or highest_iteration),
            branch=run.get("branch") or "",
            base_commit=run.get("base_commit") or "",
            plan_approved=approved,
        )
