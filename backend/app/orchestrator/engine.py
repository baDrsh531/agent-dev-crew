"""The orchestrator.

The Project Manager is not a model — it is this state machine. Transitions are
decided in code, so the sequence of work is inspectable, testable and bounded.
The models do the cognitive work inside the nodes; they never decide what
happens next.

    INTAKE -> ANALYZE -> DESIGN -> [PLAN_APPROVAL] -> IMPLEMENT -> REVIEW
                                                          ^          |
                                                          +-- FIX <--+  (bounded)
                                                                     |
                                                            DOCUMENT -> DONE

Every path out of REVIEW is bounded: the QA/Developer repair loop has a hard
iteration ceiling, and the token budget and wall clock are checked at each
transition. Exhausting any of them ends in ESCALATED, never in a silent loop.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

from pydantic import BaseModel

from ..agents.base import Agent, AgentContext, AgentError, Budget, BudgetExceeded
from ..agents.crew import build_crew
from ..agents.prompts import build_task_prompt
from ..config import ApprovalMode, Settings, get_settings
from ..domain.artifacts import (
    ChangeSet, DocsBundle, IntakeBrief, Plan, QAReport, Spec, Verdict,
)
from ..domain.events import Event, EventType
from ..domain.roles import AgentRole, RunPhase, RunStatus
from ..llm.base import LLMClient
from ..llm.factory import build_client
from ..store.broker import EventBroker, get_broker
from ..store.database import Database, get_database
from ..quality import evidence as evidence_module
from ..tools.base import ToolContext
from ..tools.shell import run_suite
from ..workspace import repomap
from ..workspace.sandbox import Sandbox
from ..workspace.worktree import Worktree
from .resume import ResumeState

MAX_DIFF_CHARS = 20_000
CANCELLED_REASON = "run cancelled"
TEST_DIRECTORIES = ("tests", "test", "spec", "__tests__")


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:limit].rstrip("-")) or "task"


class RunCancelled(Exception):
    pass


class Escalation(Exception):
    """A limit was reached, or a gate was refused. The human takes over."""


class RunEngine:
    """Executes one run. One engine instance per run, held by the service."""

    def __init__(
        self,
        run_id: str,
        request: str,
        *,
        settings: Settings | None = None,
        sandbox: Sandbox | None = None,
        llm: LLMClient | None = None,
        db: Database | None = None,
        broker: EventBroker | None = None,
        resume: ResumeState | None = None,
        worktree: Worktree | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.resume = resume or ResumeState()
        self.run_id = run_id
        self.request = request
        self.sandbox = sandbox or Sandbox(self.settings.workspace_root)
        self.llm = llm or build_client(self.settings)
        self.db = db or get_database()
        self.broker = broker or get_broker()
        self.crew: dict[AgentRole, Agent] = build_crew(self.settings)

        self.phase = RunPhase.INTAKE
        self.status = RunStatus.PENDING
        self.qa_iterations = self.resume.qa_iterations
        self.budget = Budget(
            max_tokens=self.settings.max_tokens_per_run,
            max_tool_calls=self.settings.max_tool_calls_per_agent,
        )
        # When the service hands over a worktree, the run already has its own
        # checkout on its own branch: nothing here creates or switches branches.
        self.worktree = worktree
        self.branch = ""
        self.base_commit = ""
        self.repo_map = ""
        self.baseline = ""
        # What the engineering team works from: the intake agent's precise
        # rewrite when there is one, otherwise the user's words verbatim.
        self.effective_request = request
        self.brief: IntakeBrief | None = None

        self._started_at = 0.0
        self._paused_seconds = 0.0
        self._pending: dict[str, asyncio.Future[tuple[bool, str]]] = {}
        self._cancelled = False

    # -- event plumbing ---------------------------------------------------

    async def _emit(
        self,
        type: EventType,
        payload: dict[str, Any] | None = None,
        *,
        role: AgentRole | None = None,
    ) -> Event:
        # Built directly rather than through event(**payload): a payload key
        # named "phase" or "role" would otherwise collide with the parameters.
        evt = Event(
            run_id=self.run_id,
            type=type,
            phase=self.phase,
            role=role,
            payload=payload or {},
        )
        self.db.append_event(evt)
        await self.broker.publish(self.run_id, evt.to_sse())
        return evt

    def _agent_emitter(self, role: AgentRole):
        async def emit(type: EventType, payload: dict[str, Any]) -> None:
            await self._emit(type, payload, role=role)

        return emit

    async def _set_status(self, status: RunStatus) -> None:
        self.status = status
        self.db.update_run(self.run_id, status=status.value)
        await self._emit(EventType.RUN_STATUS_CHANGED, {"status": status.value})

    async def _enter(self, phase: RunPhase) -> None:
        self._guard()
        self.phase = phase
        self.db.update_run(self.run_id, phase=phase.value)
        await self._emit(EventType.PHASE_STARTED, {"phase": phase.value})

    # -- limits -----------------------------------------------------------

    @property
    def elapsed_seconds(self) -> float:
        """Wall clock spent working. Time blocked on a human does not count —
        a reviewer taking a coffee break must not fail the run."""
        if not self._started_at:
            return 0.0
        return (time.monotonic() - self._started_at) - self._paused_seconds

    def _guard(self) -> None:
        if self._cancelled:
            raise RunCancelled("cancelled by the user")
        if self.elapsed_seconds > self.settings.max_wall_clock_seconds:
            raise Escalation(
                f"wall clock exceeded ({self.elapsed_seconds:.0f}s > "
                f"{self.settings.max_wall_clock_seconds}s of active work)"
            )
        self.budget.check_tokens()

    # -- human gates ------------------------------------------------------

    async def _ask_human(self, tool: str, summary: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        approval_id = uuid.uuid4().hex
        self.db.create_approval(approval_id, self.run_id, tool, summary, tool_input)
        future: asyncio.Future[tuple[bool, str]] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = future

        previous_status = self.status
        await self._set_status(RunStatus.WAITING_FOR_HUMAN)
        await self._emit(
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": approval_id,
                "tool": tool,
                "summary": summary,
                "input": tool_input,
            },
        )

        paused_at = time.monotonic()
        try:
            approved, reason = await future
        except asyncio.CancelledError:
            self.db.resolve_approval(approval_id, False, CANCELLED_REASON)
            raise
        finally:
            self._paused_seconds += time.monotonic() - paused_at
            self._pending.pop(approval_id, None)

        await self._emit(
            EventType.APPROVAL_RESOLVED,
            {"approval_id": approval_id, "approved": approved, "reason": reason},
        )
        await self._set_status(previous_status)
        return approved, reason

    def resolve_approval(self, approval_id: str, approved: bool, reason: str = "") -> bool:
        """Called from the API thread when a human answers. Idempotent."""
        future = self._pending.get(approval_id)
        if future is None or future.done():
            return False
        self.db.resolve_approval(approval_id, approved, reason)
        future.get_loop().call_soon_threadsafe(future.set_result, (approved, reason))
        return True

    def cancel(self) -> None:
        self._cancelled = True
        # Copied deliberately: resolving a future lets the awaiting coroutine
        # resume and pop its own entry, which would resize the dict mid-loop.
        for approval_id, future in list(self._pending.items()):
            if not future.done():
                self.db.resolve_approval(approval_id, False, CANCELLED_REASON)
                future.get_loop().call_soon_threadsafe(future.set_result, (False, CANCELLED_REASON))

    # -- artifacts --------------------------------------------------------

    async def _record(self, kind: str, artifact: BaseModel, iteration: int = 0) -> None:
        payload = artifact.model_dump(mode="json")
        self.db.save_artifact(self.run_id, kind, payload, iteration)
        await self._emit(
            EventType.ARTIFACT_PRODUCED,
            {"kind": kind, "iteration": iteration, "artifact": payload},
        )

    def _context(self, role: AgentRole) -> AgentContext:
        return AgentContext(
            run_id=self.run_id,
            sandbox=self.sandbox,
            llm=self.llm,
            budget=self.budget,
            emit=self._agent_emitter(role),
            request_approval=self._ask_human,
            approval_mode=self.settings.approval_mode.value,
        )

    async def _invoke(self, role: AgentRole, task: str) -> Any:
        outcome = await self.crew[role].run(task, self._context(role))
        self.db.update_run(
            self.run_id,
            tokens_used=self.budget.tokens_used,
            cost_usd=round(self.budget.cost_usd, 6),
        )
        return outcome.artifact

    # -- workspace --------------------------------------------------------

    def _prepare_workspace(self) -> None:
        """Isolate the run on its own branch so every change is reversible."""
        if self.worktree is not None:
            # The checkout was created on its branch before the engine started,
            # and it is nobody else's — no branching, no checkout, no reset.
            self.branch = self.worktree.branch
            self.base_commit = self.worktree.base_commit
            self.db.update_run(
                self.run_id,
                branch=self.branch,
                base_commit=self.base_commit,
                worktree_path=str(self.worktree.path),
            )
            return

        if self.resume.branch and self.sandbox.is_git_repo():
            # Resuming: rejoin the branch the interrupted run was building on,
            # rather than branching again and stranding its commits.
            self.branch = self.resume.branch
            self.base_commit = self.resume.base_commit
            checkout = self.sandbox.git("checkout", self.branch)
            if checkout.returncode != 0:
                raise Escalation(
                    f"cannot resume: branch {self.branch} is missing from "
                    f"{self.sandbox.root} ({checkout.stderr.strip()})"
                )
            return

        # `git` answers questions about the nearest repository *up the tree*,
        # not about this directory. So a workspace nested inside any other
        # checkout silently adopted it: the crew branched and committed in the
        # parent instead of provisioning its own. It went unnoticed for as long
        # as this project itself was not a repository.
        if not self.sandbox.owns_git_repo():
            if self.settings.workspace_template is None:
                # Defence in depth: preflight already refuses this. The crew
                # initialises a repository it provisioned, never one it found.
                raise Escalation(
                    f"{self.sandbox.root} is not a git repository and was not "
                    "provisioned by the crew — refusing to run git init on it"
                )
            self.sandbox.git("init")
            self.sandbox.git("add", "-A")
            self.sandbox.git("-c", "user.email=crew@local", "-c", "user.name=Agent Crew",
                             "commit", "-m", "baseline before agent run", "--allow-empty")
        self.base_commit = self.sandbox.git("rev-parse", "HEAD").stdout.strip()

        # The readable part of the name is the same for every run of one task,
        # so repetitions collided — and the failure was never read, leaving the
        # database claiming a branch the run was not on. Names are now made
        # free before use, and a checkout that still fails stops the run.
        self.branch = self.sandbox.free_branch(
            f"agent/{self.run_id[:8]}-{slugify(self.request)}"
        )
        checkout = self.sandbox.git("checkout", "-b", self.branch)
        if checkout.returncode != 0:
            raise Escalation(
                f"could not put run {self.run_id[:8]} on its own branch "
                f"{self.branch}: {checkout.stderr.strip()}"
            )
        self.db.update_run(self.run_id, branch=self.branch, base_commit=self.base_commit)

    async def _record_baseline(self) -> None:
        """Run the suite before the crew touches anything.

        Without this, "17/17 green" at the end proves nothing about
        regressions: nobody established that the suite was green to begin with.
        The result is given to QA so its verdict compares against a known start
        rather than an assumed one.
        """
        if not any((self.sandbox.root / name).is_dir() for name in TEST_DIRECTORIES):
            # Nothing to run. Spawning a test runner to watch it collect zero
            # tests costs a second and tells QA nothing it does not already know.
            self.baseline = "the project has no test directory; there is no baseline to compare against"
            return

        context = ToolContext(
            sandbox=self.sandbox, run_id=self.run_id, role=AgentRole.QA,
            request_approval=self._ask_human, approval_required=False,
        )
        result = await run_suite(context)
        self.baseline = (
            "the suite could not be run before the change"
            if result.is_error and "exit code" not in result.content
            else result.content[:2000]
        )
        await self._emit(
            EventType.LOG,
            {"message": "recorded the pre-change test baseline", "baseline": self.baseline[:600]},
        )

    def workspace_diff(self) -> str:
        if not self.sandbox.is_git_repo() or not self.base_commit:
            return ""
        result = self.sandbox.git("diff", self.base_commit, "--", ".")
        text = result.stdout
        return text[:MAX_DIFF_CHARS] + "\n... [diff truncated]" if len(text) > MAX_DIFF_CHARS else text

    # -- phases -----------------------------------------------------------

    async def _phase_intake(self, correction: str = "") -> IntakeBrief:
        """Turn what a person said into something the team can act on."""
        await self._enter(RunPhase.INTAKE)
        brief: IntakeBrief = await self._invoke(
            AgentRole.TRANSLATOR,
            build_task_prompt(
                {
                    # Always the person's own words: this agent exists to
                    # translate them, so it must never see its own rewrite.
                    "user_request": self.request,
                    "user_correction": correction,
                    "instruction": (
                        "Restate this request for the person who wrote it, and rewrite "
                        "it for the engineering team."
                        + (
                            " They rejected your previous restatement — the correction "
                            "above is what they said. Take it as authoritative and "
                            "restate again."
                            if correction
                            else ""
                        )
                    ),
                }
            ),
        )
        await self._record("intake", brief)
        return brief

    async def _phase_intake_approval(self, brief: IntakeBrief) -> tuple[bool, str]:
        """The one gate a non-developer can actually judge.

        It shows intent in their own words — not a diff, not a plan of file
        edits — so 'yes' means they understood what they agreed to.
        """
        # Kept at the middle setting too: it is the cheapest gate and the only
        # one a non-developer can actually judge, so "ask me only when it
        # matters" should still mean "confirm what I am about to build".
        if self.settings.approval_mode is ApprovalMode.AUTO:
            return True, "auto-approved"
        await self._enter(RunPhase.INTAKE_APPROVAL)
        return await self._ask_human(
            "intake",
            brief.understood_goal,
            {
                "understood_goal": brief.understood_goal,
                "steps": brief.proposed_steps,
                "clarifications": [c.model_dump(mode="json") for c in brief.clarifications],
                "out_of_scope": brief.out_of_scope,
                "risk": brief.risk_note,
            },
        )

    async def _run_intake(self) -> tuple[str, IntakeBrief | None]:
        """Returns the request the rest of the team will work from.

        Bounded like every other loop: if the human keeps rejecting the
        restatement, the run escalates instead of asking forever.
        """
        if not self.settings.intake_enabled:
            return self.request, None

        correction = ""
        for attempt in range(1, self.settings.max_intake_rounds + 1):
            brief = await self._phase_intake(correction)
            approved, reason = await self._phase_intake_approval(brief)
            if approved:
                await self._emit(
                    EventType.HANDOFF,
                    {
                        "from": AgentRole.TRANSLATOR.value,
                        "to": AgentRole.ANALYST.value,
                        "artifact": "intake",
                        "rounds": attempt,
                    },
                )
                return brief.technical_request or self.request, brief
            correction = reason
        raise Escalation(
            f"the request was still not agreed after {self.settings.max_intake_rounds} "
            "restatements — a human should rewrite it directly"
        )

    async def _phase_analyze(self) -> Spec:
        await self._enter(RunPhase.ANALYZE)
        files = "\n".join(self.sandbox.list_files(limit=120))
        spec: Spec = await self._invoke(
            AgentRole.ANALYST,
            build_task_prompt(
                {
                    "user_request": self.effective_request,
                    "workspace_files": files,
                    "instruction": "Produce the functional specification for this request.",
                }
            ),
        )
        await self._record("spec", spec)
        await self._emit(
            EventType.HANDOFF,
            {"from": AgentRole.ANALYST.value, "to": AgentRole.ARCHITECT.value, "artifact": "spec"},
        )
        return spec

    async def _phase_design(self, spec: Spec) -> Plan:
        await self._enter(RunPhase.DESIGN)
        plan: Plan = await self._invoke(
            AgentRole.ARCHITECT,
            build_task_prompt(
                {
                    "user_request": self.effective_request,
                    "specification": spec.model_dump_json(indent=2),
                    "instruction": (
                        "Read the codebase, then produce the technical plan. Every user "
                        "story must be covered by at least one step."
                    ),
                }
            ),
        )
        await self._record("plan", plan)
        return plan

    async def _phase_plan_approval(self, plan: Plan) -> None:
        """A second, more technical gate — only at the strictest setting.

        Someone who asked to be bothered only for irreversible things has
        already confirmed the intent at intake; making them read a file-by-file
        plan as well is exactly the interruption they turned off.
        """
        if self.settings.approval_mode is not ApprovalMode.ASK:
            return
        await self._enter(RunPhase.PLAN_APPROVAL)
        steps = "\n".join(f"- [{s.id}] {s.action.value} {s.target}: {s.intent}" for s in plan.steps)
        approved, reason = await self._ask_human(
            "plan",
            f"Approve the technical plan ({len(plan.steps)} steps)",
            {"approach": plan.approach, "steps": steps, "risks": [r.description for r in plan.risks]},
        )
        if not approved:
            raise Escalation(f"plan rejected by the human: {reason or 'no reason given'}")

    async def _phase_implement(self, spec: Spec, plan: Plan) -> ChangeSet:
        await self._enter(RunPhase.IMPLEMENT)
        changeset: ChangeSet = await self._invoke(
            AgentRole.DEVELOPER,
            build_task_prompt(
                {
                    "specification": spec.model_dump_json(indent=2),
                    "technical_plan": plan.model_dump_json(indent=2),
                    "instruction": (
                        "Execute the plan. Run the tests before you report completion."
                    ),
                }
            ),
        )
        await self._record("changeset", changeset)
        return changeset

    async def _gather_evidence(self, diff: str) -> str:
        """Run the checks before QA reasons, so it cannot skip one by accident."""
        context = ToolContext(
            sandbox=self.sandbox, run_id=self.run_id, role=AgentRole.QA,
            request_approval=self._ask_human, approval_required=False,
        )
        evidence = await evidence_module.collect(
            self.sandbox, context, diff=diff, baseline=self.baseline
        )
        self.db.save_artifact(
            self.run_id, "evidence", evidence.as_dict(), self.qa_iterations
        )
        await self._emit(
            EventType.ARTIFACT_PRODUCED,
            {"kind": "evidence", "iteration": self.qa_iterations, "artifact": evidence.as_dict()},
            role=AgentRole.QA,
        )
        return evidence.render()

    async def _phase_review(self, spec: Spec, plan: Plan, changeset: ChangeSet) -> QAReport:
        await self._enter(RunPhase.REVIEW)
        # Taken once: the checks and the prompt must judge the same diff.
        diff = self.workspace_diff()
        report: QAReport = await self._invoke(
            AgentRole.QA,
            build_task_prompt(
                {
                    "specification": spec.model_dump_json(indent=2),
                    "verification_strategy": plan.verification_strategy,
                    "developer_report": changeset.model_dump_json(indent=2),
                    "test_baseline_before_the_change": self.baseline,
                    "automated_checks": await self._gather_evidence(diff),
                    "diff": diff,
                    "instruction": (
                        "Verify the change against the acceptance criteria. The checks "
                        "above already ran — treat their output as fact and account for "
                        "every failure in your report, rather than re-running them. "
                        "Compare against the baseline: a test that was already failing "
                        "is not a regression, and a test that stopped passing is one "
                        "even if the new feature works. A flagged secret may be a test "
                        "fixture — say which, and why."
                    ),
                }
            ),
        )
        await self._record("qa_report", report, iteration=self.qa_iterations)
        await self._emit(
            EventType.DECISION_RECORDED,
            {"decision": "qa_verdict", "verdict": report.verdict.value, "iteration": self.qa_iterations},
            role=AgentRole.QA,
        )
        return report

    async def _phase_fix(self, spec: Spec, plan: Plan, report: QAReport) -> ChangeSet:
        await self._enter(RunPhase.FIX)
        findings = "\n".join(
            f"- [{f.severity.value}] {f.file}:{f.line} {f.summary}\n"
            f"  reproduces when: {f.failure_scenario}\n"
            f"  suggested fix: {f.suggested_fix}"
            for f in report.findings
        )
        changeset: ChangeSet = await self._invoke(
            AgentRole.DEVELOPER,
            build_task_prompt(
                {
                    "specification": spec.model_dump_json(indent=2),
                    "technical_plan": plan.model_dump_json(indent=2),
                    "qa_findings": findings,
                    "uncovered_stories": ", ".join(report.uncovered_stories),
                    "instruction": (
                        "QA rejected the change. Fix exactly what is listed above and "
                        "nothing else, then re-run the tests."
                    ),
                }
            ),
        )
        await self._record("changeset", changeset, iteration=self.qa_iterations)
        return changeset

    async def _phase_document(self, spec: Spec, changeset: ChangeSet, report: QAReport) -> DocsBundle:
        await self._enter(RunPhase.DOCUMENT)
        docs: DocsBundle = await self._invoke(
            AgentRole.DOCUMENTER,
            build_task_prompt(
                {
                    "user_request": self.effective_request,
                    "specification": spec.model_dump_json(indent=2),
                    "developer_report": changeset.model_dump_json(indent=2),
                    "qa_summary": report.summary,
                    "diff": self.workspace_diff(),
                    "instruction": "Document the change that was actually made.",
                }
            ),
        )
        await self._record("docs_bundle", docs)
        return docs

    # -- the run ----------------------------------------------------------

    async def run(self) -> RunStatus:
        self._started_at = time.monotonic()
        await self._set_status(RunStatus.RUNNING)
        state = self.resume

        if state.is_fresh:
            await self._emit(EventType.RUN_CREATED, {"request": self.request})
        else:
            await self._emit(
                EventType.LOG,
                {
                    "message": f"resuming at {state.next_phase.value}",
                    "have": [k for k, v in (
                        ("spec", state.spec), ("plan", state.plan),
                        ("changeset", state.changeset), ("qa_report", state.report),
                    ) if v is not None],
                },
            )

        try:
            self._prepare_workspace()
            await self._emit(
                EventType.LOG,
                {"message": f"working on branch {self.branch} from {self.base_commit[:8]}"},
            )

            # Static analysis, no model and no tool calls. Off by default: it
            # measured worse than not doing it — see Settings.repo_map_enabled.
            if self.settings.repo_map_enabled:
                self.repo_map = repomap.build(self.sandbox)
            if self.repo_map:
                self.crew = build_crew(self.settings, self.repo_map)
                await self._emit(
                    EventType.LOG,
                    {"message": f"indexed the workspace ({len(self.repo_map)} chars of map)"},
                )
            await self._record_baseline()

            if state.is_fresh:
                self.effective_request, self.brief = await self._run_intake()

            # Each phase is skipped when its artifact already exists, so a
            # resumed run redoes only the phase that was interrupted.
            spec = state.spec or await self._phase_analyze()
            plan = state.plan or await self._phase_design(spec)
            if not state.plan_approved:
                await self._phase_plan_approval(plan)
            changeset = state.changeset or await self._phase_implement(spec, plan)
            report = state.report or await self._phase_review(spec, plan, changeset)

            while report.verdict is Verdict.FAIL:
                if self.qa_iterations >= self.settings.max_qa_iterations:
                    raise Escalation(
                        f"QA still failing after {self.qa_iterations} repair "
                        f"iterations (limit {self.settings.max_qa_iterations}). "
                        "A human should look at the findings."
                    )
                self.qa_iterations += 1
                self.db.update_run(self.run_id, qa_iterations=self.qa_iterations)
                changeset = await self._phase_fix(spec, plan, report)
                report = await self._phase_review(spec, plan, changeset)

            if state.docs is None:
                await self._phase_document(spec, changeset, report)
            await self._enter(RunPhase.DONE)
            await self._finish(RunStatus.SUCCEEDED)

        except RunCancelled as exc:
            await self._fail(RunStatus.CANCELLED, RunPhase.FAILED, str(exc))
        except (Escalation, BudgetExceeded) as exc:
            await self._emit(EventType.LIMIT_REACHED, {"reason": str(exc)})
            await self._fail(RunStatus.ESCALATED, RunPhase.ESCALATED, str(exc))
        except AgentError as exc:
            await self._fail(RunStatus.FAILED, RunPhase.FAILED, str(exc))
        except Exception as exc:  # unexpected: record it, do not swallow it
            await self._fail(RunStatus.FAILED, RunPhase.FAILED, f"{type(exc).__name__}: {exc}")

        return self.status

    async def _finish(self, status: RunStatus) -> None:
        self.db.update_run(
            self.run_id,
            status=status.value,
            phase=self.phase.value,
            tokens_used=self.budget.tokens_used,
            cost_usd=round(self.budget.cost_usd, 6),
        )
        self.status = status
        await self._emit(
            EventType.RUN_FINISHED,
            {
                "status": status.value,
                "branch": self.branch,
                "qa_iterations": self.qa_iterations,
                "budget": self.budget.as_dict(),
                "elapsed_seconds": round(self.elapsed_seconds, 1),
            },
        )

    async def _fail(self, status: RunStatus, phase: RunPhase, error: str) -> None:
        self.phase = phase
        self.db.update_run(self.run_id, error=error, phase=phase.value)
        await self._emit(EventType.AGENT_FAILED, {"error": error})
        await self._finish(status)
