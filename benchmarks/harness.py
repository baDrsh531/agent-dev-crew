"""Benchmark harness.

A crew that writes its own tests can pass them by writing weak ones. So each
task ships **hidden acceptance tests** that are copied into the workspace only
*after* the run finishes — the crew never sees them, cannot tune to them, and
cannot delete them. A task counts as passed when the hidden tests go green
*and* the pre-existing suite has not regressed.

Every run starts from a workspace re-provisioned from the pristine template, so
results are comparable across runs and across models.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import ApprovalMode, Settings, get_settings  # noqa: E402
from app.llm.factory import build_client, lease_client, model_for  # noqa: E402
from app.domain.roles import AgentRole, RunStatus  # noqa: E402
from app.orchestrator.engine import RunEngine  # noqa: E402
from app.store.broker import EventBroker  # noqa: E402
from app.store.database import Database  # noqa: E402
from app.workspace import worktree  # noqa: E402
from app.workspace.provision import provision  # noqa: E402
from app.workspace.sandbox import Sandbox  # noqa: E402
from stats import Distribution, TaskAggregate, aggregate, compare, render_comparison  # noqa: E402

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
HIDDEN_TEST_NAME = "test_acceptance_hidden.py"
PYTEST_TIMEOUT_SECONDS = 180

_SUMMARY = re.compile(r"(\d+) (passed|failed|errors?|skipped)")


@dataclass(slots=True)
class SuiteOutcome:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    exit_code: int = -1
    detail: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors

    @property
    def all_green(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.errors == 0 and self.passed > 0


@dataclass(slots=True)
class TaskResult:
    task_id: str
    status: str
    score: str = "fail"
    repetition: int = 1
    duration_s: float = 0.0
    tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    qa_iterations: int = 0
    artifacts: list[str] = field(default_factory=list)
    own_tests: SuiteOutcome = field(default_factory=SuiteOutcome)
    hidden_tests: SuiteOutcome = field(default_factory=SuiteOutcome)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["own_tests"] = asdict(self.own_tests)
        data["hidden_tests"] = asdict(self.hidden_tests)
        return data


@dataclass(slots=True)
class Task:
    id: str
    request: str
    hidden_test: Path
    solution: Path | None

    @classmethod
    def load(cls, directory: Path) -> "Task":
        request = (directory / "request.md").read_text(encoding="utf-8").strip()
        hidden = directory / "hidden_test.py"
        if not hidden.is_file():
            raise FileNotFoundError(f"{directory.name} has no hidden_test.py")
        solution = directory / "solution"
        return cls(
            id=directory.name,
            request=request,
            hidden_test=hidden,
            solution=solution if solution.is_dir() else None,
        )


def load_tasks(only: list[str] | None = None) -> list[Task]:
    directories = sorted(d for d in TASKS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))
    tasks = [Task.load(d) for d in directories]
    if only:
        wanted = set(only)
        unknown = wanted - {t.id for t in tasks}
        if unknown:
            raise SystemExit(f"unknown task(s): {sorted(unknown)}")
        tasks = [t for t in tasks if t.id in wanted]
    return tasks


def _run_pytest(workspace: Path, target: str | None = None) -> SuiteOutcome:
    """Run the workspace suite with the harness interpreter."""
    argv = [sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider"]
    if target:
        argv.append(target)
    try:
        # Fixed executable, no shell: argv[0] is this interpreter.
        completed = subprocess.run(
            argv, cwd=workspace, capture_output=True, text=True,
            timeout=PYTEST_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return SuiteOutcome(exit_code=-1, detail=f"pytest timed out after {PYTEST_TIMEOUT_SECONDS}s")

    output = f"{completed.stdout}\n{completed.stderr}"
    outcome = SuiteOutcome(exit_code=completed.returncode, detail=output.strip()[-1500:])
    for count, kind in _SUMMARY.findall(output):
        if kind == "passed":
            outcome.passed = int(count)
        elif kind == "failed":
            outcome.failed = int(count)
        elif kind.startswith("error"):
            outcome.errors = int(count)
    return outcome


# A model server that goes away mid-pass is not a result about the crew, and
# recording it as one is worse than recording nothing. It happened: two of
# three `tag_validation` repetitions never reached a model, and the report read
# `1/3 ⚠︎ flaky`, median 135,634 tokens, range 1,713–231,852 — an accusation
# against the crew, in the same column and the same median as real outcomes.
INFRASTRUCTURE_ERRORS = ("EndpointUnavailable", "AllEndpointsDown")


def is_infrastructure_failure(error: str) -> bool:
    """Did this run fail because nothing answered, rather than on its merits?"""
    return error.split(":", 1)[0].strip() in INFRASTRUCTURE_ERRORS


def _score(status: str, own: SuiteOutcome, hidden: SuiteOutcome) -> str:
    """What the crew actually delivered, judged separately from how it got there.

    Two different failures were being conflated at first: "the code does not
    work" and "the code works but the run did not finish cleanly". A run that
    blew its token budget after producing a correct implementation is not the
    same result as one that produced nothing, and a benchmark that scores both
    `fail` cannot tell you which lever to pull. `status` stays in the report as
    its own column.
    """
    if own.total > 0 and not own.all_green:
        return "regression"          # broke what already worked — the worst outcome
    if hidden.all_green:
        # Delivered. `partial` when the orchestration did not finish cleanly:
        # the deliverable is there, the process was not.
        return "pass" if status == RunStatus.SUCCEEDED.value else "partial"
    if hidden.passed > 0:
        return "partial"
    return "fail"


@contextlib.contextmanager
def _task_workspace(settings: Settings, run_id: str, request: str, *, isolated: bool, keep: bool):
    """A pristine checkout for one task, and its cleanup.

    Sequentially, tasks share one directory re-provisioned from the template
    between them — the cheapest thing that gives comparable starting states.
    Concurrently that is exactly wrong: two tasks would edit the same files and
    each would reset the other mid-run. So a concurrent task gets its own git
    worktree, branched from the same base commit, which is the same guarantee
    for a fraction of the copying.
    """
    if not isolated:
        provision(settings.workspace_root, settings.workspace_template, force=True)
        try:
            yield settings.workspace_root
        finally:
            if not keep:
                provision(settings.workspace_root, settings.workspace_template, force=True)
        return

    checkout = worktree.create(settings.workspace_root, run_id, request)
    try:
        yield checkout.path
    finally:
        if not keep:
            checkout.remove()


async def run_task(
    task: Task,
    settings: Settings,
    *,
    keep_workspace: bool = False,
    isolated: bool = False,
    db: Database | None = None,
    llm: Any | None = None,
) -> TaskResult:
    """Provision, run the crew, then judge with tests it never saw."""
    run_id = f"bench-{task.id}-{uuid.uuid4().hex[:6]}"
    # One database for the whole suite when the caller owns it: concurrent
    # tasks opening their own connections to the same file would contend for
    # the write lock for no benefit.
    owns_db = db is None
    db = db or Database(settings.database_path)
    started = time.monotonic()

    try:
        with _task_workspace(
            settings, run_id, task.request, isolated=isolated, keep=keep_workspace
        ) as workspace:
            return await _run_in(task, settings, run_id, workspace, db, llm, started)
    except Exception as exc:  # a harness crash must not lose the other tasks
        return TaskResult(
            task_id=task.id, status="harness_error",
            duration_s=round(time.monotonic() - started, 1),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if owns_db:
            db.close()


async def _run_in(
    task: Task,
    settings: Settings,
    run_id: str,
    workspace: Path,
    db: Database,
    llm: Any | None,
    started: float,
) -> TaskResult:
    db.create_run(run_id, task.request, title=f"benchmark:{task.id}")
    engine = RunEngine(
        run_id, task.request,
        settings=settings.model_copy(update={"workspace_root": workspace}),
        sandbox=Sandbox(workspace),
        llm=llm or build_client(settings), db=db, broker=EventBroker(),
    )
    status = await engine.run()

    result = TaskResult(
        task_id=task.id,
        status=status.value,
        duration_s=round(time.monotonic() - started, 1),
        tokens=engine.budget.tokens_used,
        cost_usd=round(engine.budget.cost_usd, 6),
        tool_calls=engine.budget.tool_calls_used,
        qa_iterations=engine.qa_iterations,
        artifacts=[a["kind"] for a in db.get_artifacts(run_id)],
        error=db.get_run(run_id).get("error", "") or "",
    )

    if is_infrastructure_failure(result.error):
        # Nothing to judge. The tests would grade whatever half-written state
        # the disconnection left behind, and that score would be about the
        # network. `unusable` is excluded from every aggregate rather than
        # averaged into one.
        result.score = "unusable"
        return result

    # The suite as the crew left it: catches regressions and weak self-testing.
    result.own_tests = _run_pytest(workspace)

    # Then the tests it never saw.
    hidden_target = workspace / "tests" / HIDDEN_TEST_NAME
    hidden_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(task.hidden_test, hidden_target)
    result.hidden_tests = _run_pytest(workspace, f"tests/{HIDDEN_TEST_NAME}")
    hidden_target.unlink(missing_ok=True)

    result.score = _score(result.status, result.own_tests, result.hidden_tests)
    return result


def benchmark_settings(
    base: Settings | None = None,
    max_tokens: int | None = None,
    max_tool_calls: int | None = None,
    temperature: float | None = 0.0,
) -> Settings:
    """Gates off, generous clock: a benchmark measures the crew, not a reviewer.

    The ceilings are parameters rather than edits to `.env` because they change
    *what is being measured*. "Does this task fit in 400k tokens and 40 tool
    calls?" and "can the crew do it at all, given room?" are different
    questions, and an answer is only meaningful next to the ceilings it was
    measured under — so both are recorded in the results.

    `temperature=0` by default. Sampled decoding made three identical requests
    return three different plans, and that noise swamped every effect worth
    measuring. Greedy decoding is a *proxy* for production behaviour rather
    than production behaviour itself — but a stable proxy that detects a
    regression beats an unstable direct measure that detects nothing. Pass
    `temperature=None` to measure the sampled behaviour instead.
    """
    base = base or get_settings()
    update: dict[str, Any] = {
        "approval_mode": ApprovalMode.AUTO,
        # Benchmark requests are already precise engineering statements, so
        # intake has nothing to translate. Leaving it on would add a phase and
        # its tokens to every measurement without changing what is measured.
        "intake_enabled": False,
        "workspace_root": base.workspace_root.parent / "bench-workspace",
        "database_path": base.database_path.parent / "benchmarks.db",
    }
    if max_tokens is not None:
        update["max_tokens_per_run"] = max_tokens
    if max_tool_calls is not None:
        update["max_tool_calls_per_agent"] = max_tool_calls
    if temperature is not None:
        update["openai_temperature"] = temperature
    return base.model_copy(update=update)


def _schedule(tasks: list[Task], repeat: int) -> list[tuple[Task, int]]:
    """Repetitions interleaved by task rather than by round.

    A suite interrupted halfway then leaves a usable, if smaller, sample for
    each task instead of a complete sample for some and none for the rest.
    """
    return [(task, repetition) for task in tasks for repetition in range(1, repeat + 1)]


async def run_suite(
    tasks: list[Task],
    settings: Settings,
    *,
    keep_workspace: bool = False,
    repeat: int = 1,
    concurrency: int = 1,
) -> list[TaskResult]:
    """Run every task `repeat` times, up to `concurrency` at once.

    Concurrency above 1 is only meaningful with as many model servers: a local
    server answers one request at a time, so two runs sharing one server take
    the same total time and each reports double the duration. `main` therefore
    defaults it to the number of configured servers rather than to the number
    of cores.
    """
    schedule = _schedule(tasks, repeat)
    total = len(schedule)
    if concurrency <= 1:
        return await _run_sequentially(schedule, settings, keep_workspace, total)
    return await _run_concurrently(schedule, settings, keep_workspace, total, concurrency)


def _report(step: int, total: int, task: Task, repetition: int, repeat: int, result: TaskResult) -> None:
    label = task.id + (f" [{repetition}/{repeat}]" if repeat > 1 else "")
    print(
        f"[{step}/{total}] {label}: {result.score.upper()}  "
        f"({result.duration_s}s, {result.tokens} tokens, "
        f"hidden {result.hidden_tests.passed}/{result.hidden_tests.total or '?'})",
        flush=True,
    )


async def _run_sequentially(
    schedule: list[tuple[Task, int]], settings: Settings, keep_workspace: bool, total: int
) -> list[TaskResult]:
    repeat = max((r for _t, r in schedule), default=1)
    results: list[TaskResult] = []
    db = Database(settings.database_path)
    try:
        for step, (task, repetition) in enumerate(schedule, start=1):
            result = await run_task(task, settings, keep_workspace=keep_workspace, db=db)
            result.repetition = repetition
            _report(step, total, task, repetition, repeat, result)
            results.append(result)
            if result.score == "unusable":
                # Stop rather than grind through the rest against a server that
                # is not there. The pass this rule was written for spent sixteen
                # hours doing exactly that and produced a table that read like a
                # finding. A short pass that says why it stopped is worth more
                # than a complete one that has to be thrown away.
                print(
                    f"\nStopped after {step}/{total}: {result.error}\n"
                    "No model answered, so the remaining runs would measure the "
                    "outage. Nothing here is comparable — restart the pass once "
                    "the server is back.",
                    flush=True,
                )
                break
    finally:
        db.close()
    return results


async def _run_concurrently(
    schedule: list[tuple[Task, int]],
    settings: Settings,
    keep_workspace: bool,
    total: int,
    concurrency: int,
) -> list[TaskResult]:
    """Each task in its own checkout, pinned to its own model server."""
    repeat = max((r for _t, r in schedule), default=1)
    # The base repository is prepared once, here: `provision(force=True)` wipes
    # the directory, so doing it per task would delete the .git every worktree
    # is branched from.
    provision(settings.workspace_root, settings.workspace_template, force=True)
    worktree.ensure_base_repo(settings.workspace_root)

    db = Database(settings.database_path)
    gate = asyncio.Semaphore(concurrency)
    done = 0

    async def one(task: Task, repetition: int) -> TaskResult:
        nonlocal done
        async with gate:
            # Same composition the service uses, so a benchmark measures the
            # configuration that actually runs rather than a simpler one.
            client, release = lease_client(settings)
            try:
                result = await run_task(
                    task, settings, keep_workspace=keep_workspace,
                    isolated=True, db=db, llm=client,
                )
            finally:
                release()
        result.repetition = repetition
        done += 1
        _report(done, total, task, repetition, repeat, result)
        return result

    try:
        return list(await asyncio.gather(*(one(t, r) for t, r in schedule)))
    finally:
        db.close()
        worktree.prune(settings.workspace_root)


# --------------------------------------------------------------------------
# self-validation
# --------------------------------------------------------------------------


def _apply_solution(solution: Path, workspace: Path) -> None:
    for source in solution.rglob("*"):
        if source.is_file():
            target = workspace / source.relative_to(solution)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def validate_task(task: Task, settings: Settings) -> list[str]:
    """A benchmark whose tests are wrong measures nothing. Prove they are not.

    Two properties, checked against the pristine template:

    * the hidden tests must **fail** before the work is done — otherwise the
      task is already satisfied and measures nothing;
    * they must **pass** on the reference solution — otherwise the task is
      unfair or impossible, and a failure would say more about the tests than
      about the crew.
    """
    problems: list[str] = []
    workspace = settings.workspace_root
    hidden_rel = f"tests/{HIDDEN_TEST_NAME}"

    provision(workspace, settings.workspace_template, force=True)
    hidden_target = workspace / "tests" / HIDDEN_TEST_NAME
    hidden_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(task.hidden_test, hidden_target)

    baseline = _run_pytest(workspace, hidden_rel)
    if baseline.all_green:
        problems.append("hidden tests already pass on the untouched template — the task measures nothing")
    elif baseline.total == 0 and baseline.exit_code not in (1, 2):
        problems.append(f"hidden tests could not run on the template (exit {baseline.exit_code})")

    if task.solution is None:
        problems.append("no reference solution: fairness is unproven")
    else:
        _apply_solution(task.solution, workspace)
        solved = _run_pytest(workspace, hidden_rel)
        if not solved.all_green:
            problems.append(
                f"hidden tests fail on the reference solution "
                f"({solved.passed} passed, {solved.failed} failed, {solved.errors} errors) — "
                f"the task is unfair as written:\n{solved.detail[-600:]}"
            )
        regression = _run_pytest(workspace)
        if not regression.all_green:
            problems.append("the reference solution breaks the pre-existing suite")

    provision(workspace, settings.workspace_template, force=True)
    return problems


def validate_all(tasks: list[Task], settings: Settings) -> int:
    failures = 0
    for task in tasks:
        problems = validate_task(task, settings)
        if problems:
            failures += 1
            print(f"  {task.id}: INVALID")
            for problem in problems:
                print(f"      - {problem}")
        else:
            print(f"  {task.id}: ok (fails on baseline, passes on reference)")
    return failures


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

SCORE_MARK = {"pass": "PASS", "partial": "PARTIAL", "regression": "REGRESSION", "fail": "FAIL"}


def to_markdown(results: list[TaskResult], settings: Settings, *, concurrency: int = 1) -> str:
    model = model_for(AgentRole.DEVELOPER, settings)
    provider = settings.effective_provider.value
    aggregates = aggregate(results)
    repeat = max((a.n for a in aggregates), default=1)
    # `a.n` is the number of repetitions that actually ran, so `passes == n`
    # would call a task nobody measured a clean sweep. It has to have run.
    fully_passing = sum(1 for a in aggregates if a.n > 0 and a.passes == a.n)

    lines = [
        "# Benchmark results",
        "",
        f"- provider: `{provider}`",
        f"- model: `{model}`",
        f"- token budget per run: {settings.max_tokens_per_run:,}",
        f"- tool-call ceiling per agent: {settings.max_tool_calls_per_agent}",
        f"- repetitions per task: {repeat}",
        f"- concurrent runs: {concurrency}",
        f"- tasks passing every repetition: **{fully_passing}/{len(aggregates)}**",
        f"- total tokens: {sum(r.tokens for r in results):,}",
        f"- total cost: ${sum(r.cost_usd for r in results):.4f}",
        f"- total time: {sum(r.duration_s for r in results):.0f}s",
        "",
        "A task passes when the hidden acceptance tests go green *and* the",
        "pre-existing suite has not regressed. The crew never sees the hidden tests.",
    ]

    if concurrency > 1:
        lines += [
            "",
            f"> Measured with {concurrency} runs at once, each in its own git",
            "> worktree and pinned to its own model server. Tokens, tool calls and",
            "> scores are unaffected by that. **Times are only comparable to another",
            "> run at the same concurrency** — a slower server in the pool, or more",
            "> runs than servers, shows up here as duration and nowhere else.",
        ]

    if repeat == 1:
        lines += [
            "",
            "> Single run per task. This model's outcomes vary run to run, so treat",
            "> these numbers as observations, not measurements — use `--repeat 3`",
            "> before drawing a conclusion from them.",
        ]

    lines += [
        "",
        "| task | passes | scores | hidden | tool calls | tokens | time |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in aggregates:
        flag = " ⚠︎ flaky" if a.is_flaky else ""
        if a.unusable:
            # Said plainly and in the passes column, where it cannot be missed:
            # this row rests on fewer measurements than the pass asked for.
            flag += f" ⚠︎ {a.unusable} never ran"
        scores = ", ".join(SCORE_MARK.get(s, s) for s in a.scores) or "—"
        hidden = f"{a.hidden_passed.render()}/{a.hidden_total}" if a.hidden_total else "—"
        lines.append(
            f"| `{a.task_id}` | {a.passes}/{a.n}{flag} | {scores} | {hidden} | "
            f"{a.tool_calls.render()} | {a.tokens.render()} | {a.duration_s.render('s')} |"
        )

    if repeat > 1:
        lines += [
            "",
            "Values are the median, with the observed range in brackets. A task",
            "marked flaky produced different outcomes from identical inputs.",
        ]

    if any(a.unusable for a in aggregates):
        lines += [
            "",
            "> **Some repetitions never reached a model** and are excluded from",
            "> every figure above rather than averaged into one — a run that could",
            "> not call the server measures the network, not the crew. Rows marked",
            "> `never ran` rest on fewer repetitions than the pass asked for, so",
            "> treat their ranges as narrower evidence than they look.",
        ]

    failures = [r for r in results if r.score != "pass"]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines.append(f"### `{r.task_id}` — {r.score}")
            if r.error:
                lines.append(f"- run error: {r.error}")
            if r.hidden_tests.failed or r.hidden_tests.errors:
                lines.append(f"- hidden tests: {r.hidden_tests.failed} failed, {r.hidden_tests.errors} errors")
                lines.append("```")
                lines.append(r.hidden_tests.detail[-800:])
                lines.append("```")
            lines.append("")
    return "\n".join(lines)


def _code_version() -> dict[str, Any]:
    """The commit this run's code came from, and whether it was modified.

    `dirty` matters as much as the hash: a measurement taken over uncommitted
    edits cannot be reproduced from the commit alone, and saying so is cheaper
    than discovering it later.
    """
    root = Path(__file__).resolve().parents[1]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            capture_output=True, text=True, timeout=15, check=False,
        )
        status = subprocess.run(
            # Results are excluded: the previous pass writes its own summary
            # into this directory, so every pass after the first would report
            # a dirty tree for a reason that has nothing to do with the code.
            ["git", "status", "--porcelain", "--", ".", ":!benchmarks/results"],
            cwd=root, capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": "unknown", "dirty": None}
    if head.returncode != 0:
        return {"commit": "not a git repository", "dirty": None}
    return {
        "commit": head.stdout.strip(),
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def write_results(
    results: list[TaskResult], settings: Settings, *, concurrency: int = 1
) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": settings.effective_provider.value,
        "model": model_for(AgentRole.DEVELOPER, settings),
        "max_tokens_per_run": settings.max_tokens_per_run,
        "max_tool_calls_per_agent": settings.max_tool_calls_per_agent,
        # Recorded because it changes what `duration_s` means, and a later
        # comparison against a differently-paced run would otherwise read the
        # queueing as a regression.
        "concurrency": concurrency,
        # Which code produced these numbers. A measurement was once read as
        # having run with a fix that was committed while it was already in
        # flight — the process had loaded the old modules at import, and
        # nothing in the file said so. Reconstructing that from timestamps
        # afterwards took longer than recording it here ever will.
        "code_version": _code_version(),
        "results": [r.as_dict() for r in results],
        # Stored alongside the raw runs so a later comparison never has to
        # recompute — and so the sample size travels with the numbers.
        "aggregates": [a.as_dict() for a in aggregate(results)],
    }
    json_path = RESULTS_DIR / "latest.json"
    md_path = RESULTS_DIR / "latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(results, settings, concurrency=concurrency), encoding="utf-8")
    return json_path, md_path


def load_aggregates(path: Path) -> list[TaskAggregate]:
    """Rebuild aggregates from a saved result file, old or new format."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "aggregates" in payload:
        restored: list[TaskAggregate] = []
        for entry in payload["aggregates"]:
            item = TaskAggregate(task_id=entry["task_id"], scores=list(entry["scores"]))
            item.tokens = Distribution(list(entry["tokens"]["values"]))
            item.tool_calls = Distribution(list(entry["tool_calls"]["values"]))
            item.duration_s = Distribution(list(entry["duration_s"]["values"]))
            item.hidden_passed = Distribution(list(entry["hidden_passed"]["values"]))
            item.hidden_total = entry["hidden_total"]
            restored.append(item)
        return restored

    # Result files written before repetitions existed: one run per task.
    results = [
        TaskResult(
            task_id=r["task_id"], status=r["status"], score=r["score"],
            tokens=r["tokens"], tool_calls=r["tool_calls"], duration_s=r["duration_s"],
            hidden_tests=SuiteOutcome(**r["hidden_tests"]),
            own_tests=SuiteOutcome(**r["own_tests"]),
        )
        for r in payload["results"]
    ]
    return aggregate(results)


def main(argv: list[str] | None = None) -> int:
    import argparse

    # The report contains ⚠︎ and en-dashes, and a Windows console defaults to
    # cp1252. Printing it there raised UnicodeEncodeError *after* the results
    # were written but *before* `--compare` ran — so a fifty-minute run
    # produced its data and then threw away the comparison it was launched to
    # make. Reconfiguring is better than stripping the characters: the file on
    # disk is UTF-8 either way, and only the console was ever the problem.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run the agent-crew benchmark suite.")
    parser.add_argument("--tasks", nargs="*", help="Task ids to run. Default: all.")
    parser.add_argument("--keep-workspace", action="store_true",
                        help="Leave the last workspace in place for inspection.")
    parser.add_argument("--validate", action="store_true",
                        help="Check the tasks themselves: hidden tests must fail on the "
                             "template and pass on the reference solution. Runs no agents.")
    parser.add_argument("--max-tokens", type=int, default=None,
                        help="Token budget per run, overriding MAX_TOKENS_PER_RUN.")
    parser.add_argument("--max-tool-calls", type=int, default=None,
                        help="Tool-call ceiling per agent, overriding "
                             "MAX_TOOL_CALLS_PER_AGENT.")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="Run each task N times. This model's outcomes vary "
                             "run to run; a single run cannot tell a real effect "
                             "from noise. Use 3 or more before concluding anything.")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Decoding temperature. 0 (the default) is greedy and "
                             "near-deterministic, which is what makes a comparison "
                             "readable. Pass -1 to use the server's own sampling.")
    parser.add_argument("--concurrency", type=int, default=None, metavar="N",
                        help="Run N tasks at once, each in its own checkout and "
                             "pinned to its own model server. Defaults to the "
                             "number of servers in OPENAI_BASE_URL. Going above "
                             "that makes runs queue on a shared server, which "
                             "inflates every reported duration.")
    parser.add_argument("--compare", metavar="RESULTS.json",
                        help="Compare against an earlier result file instead of "
                             "running anything, or after running with --repeat.")
    args = parser.parse_args(argv)

    if args.compare and not args.tasks and args.repeat == 1 and not args.validate:
        # Bare --compare: judge the last run against the given baseline.
        latest = RESULTS_DIR / "latest.json"
        if not latest.is_file():
            print("no results/latest.json to compare — run the suite first")
            return 1
        report = render_comparison(
            compare(load_aggregates(Path(args.compare)), load_aggregates(latest))
        )
        print(report)
        (RESULTS_DIR / "comparison.md").write_text(report, encoding="utf-8")
        return 0

    tasks = load_tasks(args.tasks)
    settings = benchmark_settings(
        max_tokens=args.max_tokens,
        max_tool_calls=args.max_tool_calls,
        temperature=None if args.temperature < 0 else args.temperature,
    )

    if args.validate:
        print(f"validating {len(tasks)} task(s) — no model is called\n")
        failures = validate_all(tasks, settings)
        print(f"\n{len(tasks) - failures}/{len(tasks)} task(s) valid")
        return 1 if failures else 0

    servers = max(1, len(settings.openai_base_urls))
    concurrency = max(1, args.concurrency if args.concurrency is not None else servers)

    print(f"provider={settings.effective_provider.value} "
          f"model={model_for(AgentRole.DEVELOPER, settings)} "
          f"budget={settings.max_tokens_per_run:,} "
          f"tools={settings.max_tool_calls_per_agent} "
          f"tasks={len(tasks)} repeat={args.repeat} concurrency={concurrency}")
    if concurrency > servers:
        print(f"warning: {concurrency} concurrent runs over {servers} model server(s). "
              "Runs will queue on a shared server and every reported duration will "
              "include that wait — tokens and scores stay valid, times do not.")
    print()

    started = time.monotonic()
    results = asyncio.run(
        run_suite(
            tasks, settings, keep_workspace=args.keep_workspace,
            repeat=args.repeat, concurrency=concurrency,
        )
    )
    wall_clock = time.monotonic() - started
    json_path, md_path = write_results(results, settings, concurrency=concurrency)

    print()
    print(to_markdown(results, settings, concurrency=concurrency))
    print(f"\nwall clock: {wall_clock:.0f}s for {sum(r.duration_s for r in results):.0f}s of run time")
    print(f"\nwritten: {md_path}  {json_path}")

    if args.compare:
        comparison = compare(load_aggregates(Path(args.compare)), aggregate(results))
        report = render_comparison(comparison)
        print()
        print(report)
        (RESULTS_DIR / "comparison.md").write_text(report, encoding="utf-8")

    return 0 if all(a.passes == a.n for a in aggregate(results)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
