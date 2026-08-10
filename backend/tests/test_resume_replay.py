"""Resume an interrupted run; replay a finished one without a model."""

from __future__ import annotations

from app.domain.roles import RunPhase, RunStatus
from app.llm.replay import ReplayExhausted, ReplayLLMClient
from app.orchestrator.engine import RunEngine
from app.orchestrator.resume import ResumeState
from conftest import (
    RoleScriptedClient, make_changeset, make_docs, make_intake, make_plan,
    make_qa_report, make_spec,
)


def scripted(qa_verdicts=("pass",)) -> RoleScriptedClient:
    return RoleScriptedClient({
        "IntakeBrief": [make_intake()],
        "Spec": [make_spec()], "Plan": [make_plan()], "ChangeSet": [make_changeset()],
        "QAReport": [make_qa_report(v) for v in qa_verdicts], "DocsBundle": [make_docs()],
    })


def engine_for(run_id, settings, db, broker, sandbox, client, resume=None) -> RunEngine:
    return RunEngine(
        run_id, "Add JWT authentication", settings=settings, sandbox=sandbox,
        llm=client, db=db, broker=broker, resume=resume,
    )


# -- deriving the resume point ----------------------------------------------


def test_a_fresh_run_starts_at_analyze(db) -> None:
    db.create_run("r", "task")
    assert ResumeState.load(db, "r").next_phase is RunPhase.ANALYZE


def test_a_spec_alone_resumes_at_design(db) -> None:
    """The point comes from the artifacts, so it cannot drift from the record."""
    db.create_run("r", "task")
    db.save_artifact("r", "spec", make_spec().model_dump(mode="json"))
    assert ResumeState.load(db, "r").next_phase is RunPhase.DESIGN


def test_with_a_plan_but_no_approval_it_resumes_at_the_gate(db) -> None:
    db.create_run("r", "task")
    db.save_artifact("r", "spec", make_spec().model_dump(mode="json"))
    db.save_artifact("r", "plan", make_plan().model_dump(mode="json"))
    assert ResumeState.load(db, "r").next_phase is RunPhase.PLAN_APPROVAL


def test_a_changeset_implies_the_plan_was_approved(db) -> None:
    """An auto-mode run records no approval; the changeset proves it happened."""
    db.create_run("r", "task")
    for kind, artifact in (("spec", make_spec()), ("plan", make_plan()), ("changeset", make_changeset())):
        db.save_artifact("r", kind, artifact.model_dump(mode="json"))
    state = ResumeState.load(db, "r")
    assert state.plan_approved is True
    assert state.next_phase is RunPhase.REVIEW


def test_everything_present_means_nothing_to_do(db) -> None:
    db.create_run("r", "task")
    for kind, artifact in (
        ("spec", make_spec()), ("plan", make_plan()), ("changeset", make_changeset()),
        ("qa_report", make_qa_report()), ("docs_bundle", make_docs()),
    ):
        db.save_artifact("r", kind, artifact.model_dump(mode="json"))
    assert ResumeState.load(db, "r").next_phase is RunPhase.DONE


def test_an_artifact_that_no_longer_validates_is_treated_as_absent(db) -> None:
    """Schemas move on; resuming on a shape the pipeline cannot consume is worse."""
    db.create_run("r", "task")
    db.save_artifact("r", "spec", {"summary": "stale shape from an older version"})
    state = ResumeState.load(db, "r")
    assert state.spec is None
    assert state.next_phase is RunPhase.ANALYZE


# -- resuming for real -------------------------------------------------------


async def test_resume_skips_the_phases_that_already_produced_artifacts(
    settings, db, broker, sandbox
) -> None:
    # First run: interrupted after DESIGN.
    db.create_run("r1", "Add JWT authentication")
    first = engine_for("r1", settings, db, broker, sandbox, scripted())
    first._prepare_workspace()
    spec = await first._phase_analyze()
    plan = await first._phase_design(spec)
    assert plan is not None
    db.update_run("r1", branch=first.branch, base_commit=first.base_commit)

    # Resume: the analyst and architect must not run again.
    client = scripted()
    state = ResumeState.load(db, "r1")
    second = engine_for("r1", settings, db, broker, sandbox, client, resume=state)
    assert await second.run() is RunStatus.SUCCEEDED

    requested = [
        (call.output_format or {}).get("schema", {}).get("title") for call in client.calls
    ]
    assert "Spec" not in requested and "Plan" not in requested
    assert {"ChangeSet", "QAReport", "DocsBundle"} <= set(requested)


async def test_resume_rejoins_the_original_branch(settings, db, broker, sandbox) -> None:
    db.create_run("r1", "Add JWT authentication")
    first = engine_for("r1", settings, db, broker, sandbox, scripted())
    first._prepare_workspace()
    await first._phase_analyze()
    db.update_run("r1", branch=first.branch, base_commit=first.base_commit)

    second = engine_for("r1", settings, db, broker, sandbox, scripted(),
                        resume=ResumeState.load(db, "r1"))
    await second.run()

    assert second.branch == first.branch
    assert sandbox.current_branch() == first.branch


async def test_resume_carries_the_repair_counter_forward(settings, db, broker, sandbox) -> None:
    """Otherwise a crash would silently reset the bound on the repair loop."""
    db.create_run("r1", "Add JWT authentication")
    db.update_run("r1", qa_iterations=2)
    for kind, artifact in (("spec", make_spec()), ("plan", make_plan())):
        db.save_artifact("r1", kind, artifact.model_dump(mode="json"))

    engine = engine_for("r1", settings, db, broker, sandbox, scripted(),
                        resume=ResumeState.load(db, "r1"))
    assert engine.qa_iterations == 2


async def test_resuming_into_a_missing_branch_escalates(settings, db, broker, sandbox) -> None:
    db.create_run("r1", "Add JWT authentication")
    db.save_artifact("r1", "spec", make_spec().model_dump(mode="json"))
    sandbox.git("init")
    sandbox.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base", "--allow-empty")
    state = ResumeState.load(db, "r1")
    state.branch = "agent/vanished"

    engine = engine_for("r1", settings, db, broker, sandbox, scripted(), resume=state)
    assert await engine.run() is RunStatus.ESCALATED
    assert "vanished" in db.get_run("r1")["error"]


# -- replay ------------------------------------------------------------------


async def test_replay_reaches_the_same_outcome_without_a_model(
    settings, db, broker, sandbox
) -> None:
    db.create_run("original", "Add JWT authentication")
    original = engine_for("original", settings, db, broker, sandbox, scripted())
    assert await original.run() is RunStatus.SUCCEEDED

    db.create_run("replayed", "Add JWT authentication")
    client = ReplayLLMClient(db, "original")
    replayed = engine_for("replayed", settings, db, broker, sandbox, client)

    assert await replayed.run() is RunStatus.SUCCEEDED
    assert {a["kind"] for a in db.get_artifacts("replayed")} == {
        "intake", "spec", "plan", "changeset", "evidence", "qa_report", "docs_bundle"
    }
    assert replayed.budget.cost_usd == 0.0


async def test_replay_reproduces_a_recorded_repair_loop(settings, db, broker, sandbox) -> None:
    db.create_run("original", "Add JWT authentication")
    original = engine_for("original", settings, db, broker, sandbox,
                          scripted(qa_verdicts=("fail", "pass")))
    await original.run()
    assert original.qa_iterations == 1

    db.create_run("replayed", "Add JWT authentication")
    replayed = engine_for("replayed", settings, db, broker, sandbox,
                          ReplayLLMClient(db, "original"))
    await replayed.run()

    assert replayed.qa_iterations == 1, "the recorded repair loop must replay as one"


def test_replay_of_a_run_with_no_artifacts_is_reported(db) -> None:
    db.create_run("empty", "task")
    assert ReplayLLMClient(db, "empty").recorded == {}


async def test_replay_says_so_when_the_recording_runs_out(db, settings, broker, sandbox) -> None:
    """A replay that cannot answer must fail loudly, not invent an artifact."""
    db.create_run("original", "task")
    db.save_artifact("original", "spec", make_spec().model_dump(mode="json"))

    db.create_run("replayed", "task")
    engine = engine_for("replayed", settings, db, broker, sandbox,
                        ReplayLLMClient(db, "original"))
    await engine.run()

    assert db.get_run("replayed")["status"] == RunStatus.FAILED.value
    assert "ReplayExhausted" in db.get_run("replayed")["error"] or "recorded no further" in db.get_run("replayed")["error"]


def test_replay_exhausted_is_a_distinct_error() -> None:
    assert issubclass(ReplayExhausted, RuntimeError)
