"""The state machine: happy path, the bounded repair loop, and the gates.

These are the tests that matter — they prove the orchestration is deterministic
and that no path out of REVIEW is unbounded.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.config import ApprovalMode
from app.domain.events import EventType
from app.domain.roles import RunPhase, RunStatus
from app.orchestrator.engine import RunEngine
from conftest import (
    RoleScriptedClient, make_changeset, make_docs, make_intake, make_plan,
    make_qa_report, make_spec,
)

pytestmark = pytest.mark.asyncio


def build_engine(settings, db, broker, sandbox, *, qa_verdicts=("pass",)):
    client = RoleScriptedClient(
        {
            "IntakeBrief": [make_intake()],
            "Spec": [make_spec()],
            "Plan": [make_plan()],
            "ChangeSet": [make_changeset()],
            "QAReport": [make_qa_report(v) for v in qa_verdicts],
            "DocsBundle": [make_docs()],
        }
    )
    db.create_run("run-1", "Add JWT authentication")
    return RunEngine(
        "run-1", "Add JWT authentication",
        settings=settings, sandbox=sandbox, llm=client, db=db, broker=broker,
    ), client


def phases_of(db, run_id="run-1"):
    return [
        e["payload"]["phase"]
        for e in db.get_events(run_id)
        if e["type"] == EventType.PHASE_STARTED.value
    ]


async def wait_for_approval(db, run_id="run-1", timeout=20.0, expect_tool=None):
    """Poll until the run blocks on a gate. Fails loudly rather than IndexError."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        pending = db.pending_approvals(run_id)
        if pending:
            if expect_tool and pending[0]["tool"] != expect_tool:
                raise AssertionError(
                    f"expected a {expect_tool!r} gate, got {pending[0]['tool']!r}"
                )
            return pending[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"no approval was requested within {timeout}s")


async def approve_intake(db, engine):
    """In ask mode the first gate is intake — a non-developer confirms intent
    before anyone mentions a file."""
    approval = await wait_for_approval(db, expect_tool="intake")
    engine.resolve_approval(approval["id"], True, "oui, c'est ça")
    return approval


async def test_happy_path_visits_every_phase_in_order(settings, db, broker, sandbox):
    engine, _ = build_engine(settings, db, broker, sandbox)

    assert await engine.run() is RunStatus.SUCCEEDED
    assert phases_of(db) == [
        RunPhase.INTAKE.value, RunPhase.ANALYZE.value, RunPhase.DESIGN.value,
        RunPhase.IMPLEMENT.value, RunPhase.REVIEW.value, RunPhase.DOCUMENT.value,
        RunPhase.DONE.value,
    ]


async def test_the_team_works_from_the_translated_request(settings, db, broker, sandbox):
    """Intake exists to hand the team a precise request, not the user's prose."""
    engine, client = build_engine(settings, db, broker, sandbox)
    await engine.run()

    assert engine.effective_request.startswith("Add JWT bearer authentication")
    analyst_call = next(
        c for c in client.calls
        if (c.output_format or {}).get("schema", {}).get("title") == "Spec"
    )
    assert "Add JWT bearer authentication" in analyst_call.messages[0]["content"]


async def test_intake_can_be_turned_off(settings, db, broker, sandbox):
    """Requests that already arrive precise should not pay for a translation."""
    settings.intake_enabled = False
    engine, _ = build_engine(settings, db, broker, sandbox)
    await engine.run()

    assert RunPhase.INTAKE.value not in phases_of(db)
    assert engine.effective_request == "Add JWT authentication"


async def test_every_artifact_is_persisted(settings, db, broker, sandbox):
    engine, _ = build_engine(settings, db, broker, sandbox)
    await engine.run()

    kinds = {a["kind"] for a in db.get_artifacts("run-1")}
    assert kinds == {
        "intake", "spec", "plan", "changeset", "evidence", "qa_report", "docs_bundle"
    }


async def test_run_works_on_a_dedicated_branch(settings, db, broker, sandbox):
    engine, _ = build_engine(settings, db, broker, sandbox)
    await engine.run()

    assert engine.branch.startswith("agent/")
    assert sandbox.current_branch() == engine.branch
    assert engine.base_commit  # a rollback point exists


async def test_qa_failure_triggers_one_repair_iteration_then_passes(settings, db, broker, sandbox):
    engine, _ = build_engine(settings, db, broker, sandbox, qa_verdicts=("fail", "pass"))

    assert await engine.run() is RunStatus.SUCCEEDED
    assert engine.qa_iterations == 1
    assert RunPhase.FIX.value in phases_of(db)


async def test_repair_loop_is_bounded_and_escalates(settings, db, broker, sandbox):
    # max_qa_iterations is 2 in the fixture; QA never passes.
    engine, _ = build_engine(settings, db, broker, sandbox, qa_verdicts=("fail",))

    assert await engine.run() is RunStatus.ESCALATED
    assert engine.qa_iterations == settings.max_qa_iterations
    assert phases_of(db).count(RunPhase.FIX.value) == settings.max_qa_iterations
    limits = [e for e in db.get_events("run-1") if e["type"] == EventType.LIMIT_REACHED.value]
    assert limits and "repair iterations" in limits[0]["payload"]["reason"]


async def test_token_budget_exhaustion_escalates(settings, db, broker, sandbox):
    settings.max_tokens_per_run = 10  # one model call already exceeds this
    engine, _ = build_engine(settings, db, broker, sandbox)

    assert await engine.run() is RunStatus.ESCALATED
    assert db.get_run("run-1")["error"]


async def test_plan_gate_blocks_until_a_human_answers(settings, db, broker, sandbox):
    settings.approval_mode = ApprovalMode.ASK
    engine, _ = build_engine(settings, db, broker, sandbox)

    task = asyncio.create_task(engine.run())
    await approve_intake(db, engine)
    approval = await wait_for_approval(db, expect_tool="plan")
    assert engine.status is RunStatus.WAITING_FOR_HUMAN

    assert engine.resolve_approval(approval["id"], True, "looks right")
    assert await task is RunStatus.SUCCEEDED


async def test_rejecting_the_plan_escalates_without_touching_the_workspace(
    settings, db, broker, sandbox
):
    settings.approval_mode = ApprovalMode.ASK
    engine, _ = build_engine(settings, db, broker, sandbox)

    task = asyncio.create_task(engine.run())
    await approve_intake(db, engine)
    approval = await wait_for_approval(db, expect_tool="plan")
    engine.resolve_approval(approval["id"], False, "wrong approach")

    assert await task is RunStatus.ESCALATED
    assert RunPhase.IMPLEMENT.value not in phases_of(db)


async def test_human_wait_does_not_consume_the_wall_clock(settings, db, broker, sandbox):
    """A reviewer thinking for a while must not fail the run on a timeout."""
    settings.approval_mode = ApprovalMode.ASK
    engine, _ = build_engine(settings, db, broker, sandbox)

    human_thinking_time = 1.0
    started = time.monotonic()

    task = asyncio.create_task(engine.run())
    await approve_intake(db, engine)
    approval = await wait_for_approval(db, expect_tool="plan")
    await asyncio.sleep(human_thinking_time)
    engine.resolve_approval(approval["id"], True)
    assert await task is RunStatus.SUCCEEDED

    real_seconds = time.monotonic() - started
    # Real time includes the pause; the budgeted clock must not.
    assert real_seconds >= human_thinking_time
    assert engine._paused_seconds >= human_thinking_time
    assert engine.elapsed_seconds <= real_seconds - human_thinking_time + 0.2


async def test_cancelling_a_waiting_run_stops_it(settings, db, broker, sandbox):
    settings.approval_mode = ApprovalMode.ASK
    engine, _ = build_engine(settings, db, broker, sandbox)

    task = asyncio.create_task(engine.run())
    await wait_for_approval(db)
    engine.cancel()

    # Cancelling reports as cancelled, not as an escalation: nothing hit a
    # limit and nothing needs a human to look at findings — the user stopped it.
    assert await task is RunStatus.CANCELLED
    assert db.get_run("run-1")["status"] == RunStatus.CANCELLED.value
    assert RunPhase.IMPLEMENT.value not in phases_of(db)


async def test_events_are_ordered_and_gapless(settings, db, broker, sandbox):
    engine, _ = build_engine(settings, db, broker, sandbox)
    await engine.run()

    seqs = [e["seq"] for e in db.get_events("run-1")]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_subscribers_receive_the_live_stream(settings, db, broker, sandbox):
    engine, _ = build_engine(settings, db, broker, sandbox)
    queue = await broker.subscribe("run-1")

    await engine.run()

    received = []
    while not queue.empty():
        received.append(queue.get_nowait())
    assert any(e["type"] == EventType.RUN_FINISHED.value for e in received)


# -- a run never borrows someone else's repository ---------------------------


def git(cwd, *args) -> str:
    import subprocess
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, capture_output=True, text=True, check=False,
    ).stdout.strip()


async def test_a_workspace_nested_in_another_repo_makes_its_own(
    tmp_path, settings, db, broker
) -> None:
    """This is the incident, written down. Publishing the project turned its
    directory into a repository; the workspace lived inside it, and `git`
    answers about the nearest repo *up the tree* — so the crew branched and
    committed in the project's own history instead of provisioning its own."""
    from app.orchestrator.engine import RunEngine
    from app.workspace.sandbox import Sandbox

    outer = tmp_path / "outer"
    nested = outer / "data" / "workspace"
    nested.mkdir(parents=True)
    (nested / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(outer, "init")
    git(outer, "commit", "-m", "the project's own history", "--allow-empty")
    before = git(outer, "rev-parse", "HEAD")

    db.create_run("r1", "Add a thing")
    engine = RunEngine(
        "r1", "Add a thing",
        settings=settings.model_copy(update={"workspace_root": nested}),
        sandbox=Sandbox(nested), db=db, broker=broker,
    )
    engine._prepare_workspace()

    assert git(nested, "rev-parse", "--show-toplevel").endswith("workspace")
    assert git(outer, "rev-parse", "HEAD") == before, "the outer repo is untouched"
    assert git(outer, "branch", "--list", "agent/*") == "", "and gained no branch"


async def test_two_runs_of_the_same_request_get_different_branches(
    settings, db, broker, sandbox
) -> None:
    """The readable branch name is the run id prefix plus a slug of the
    request — identical for every repetition of one benchmark task. They used
    to collide, the failure was never read, and the database recorded a branch
    the run was not on."""
    from app.orchestrator.engine import RunEngine

    branches = []
    for run_id in ("bench-jw-aaaaaa", "bench-jw-bbbbbb"):
        db.create_run(run_id, "Add JWT authentication")
        engine = RunEngine(run_id, "Add JWT authentication",
                           settings=settings, sandbox=sandbox, db=db, broker=broker)
        engine._prepare_workspace()
        branches.append(engine.branch)

    assert branches[0] != branches[1]
    # And what the database says must be what git actually did.
    for run_id, branch in zip(("bench-jw-aaaaaa", "bench-jw-bbbbbb"), branches):
        assert db.get_run(run_id)["branch"] == branch
        assert branch in git(sandbox.root, "branch", "--list", branch)
