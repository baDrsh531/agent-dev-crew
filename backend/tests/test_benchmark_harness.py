"""The benchmark harness produces the headline numbers, so it gets tests too.

Scoring and output parsing are pure functions; they are checked directly rather
than by running a benchmark, which would need a model and several minutes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from harness import (  # noqa: E402
    _SUMMARY, Task, TaskResult, SuiteOutcome, _schedule, _score, benchmark_settings,
    is_infrastructure_failure, load_tasks, run_suite, to_markdown,
)


def outcome(passed=0, failed=0, errors=0, exit_code=0) -> SuiteOutcome:
    return SuiteOutcome(passed=passed, failed=failed, errors=errors, exit_code=exit_code)


GREEN = outcome(passed=5)
PARTIAL = outcome(passed=2, failed=3, exit_code=1)
DEAD = outcome(passed=0, failed=5, exit_code=1)
NOT_RUN = outcome(exit_code=-1)


# -- parsing pytest output ---------------------------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [
        ("12 passed, 1 warning in 2.4s", {("12", "passed")}),
        ("8 failed, 4 passed in 2.48s", {("8", "failed"), ("4", "passed")}),
        ("1 error in 0.3s", {("1", "error")}),
        ("2 errors, 3 passed in 1s", {("2", "errors"), ("3", "passed")}),
        ("5 skipped in 0.1s", {("5", "skipped")}),
    ],
)
def test_every_pytest_summary_shape_is_parsed(line: str, expected: set) -> None:
    assert set(_SUMMARY.findall(line)) == expected


def test_a_suite_that_collected_nothing_is_not_green() -> None:
    """Exit 0 with zero tests must not read as success."""
    assert outcome(passed=0, exit_code=0).all_green is False


# -- scoring -----------------------------------------------------------------


def test_delivered_and_finished_cleanly_is_a_pass() -> None:
    assert _score("succeeded", GREEN, GREEN) == "pass"


def test_delivered_but_escalated_is_partial_not_fail() -> None:
    """Blowing the budget after producing correct code is a process failure,
    not a capability failure — and the two need different fixes."""
    assert _score("escalated", GREEN, GREEN) == "partial"


def test_breaking_the_existing_suite_outranks_everything() -> None:
    """Damaging working code is the worst outcome, even with hidden tests green."""
    assert _score("succeeded", PARTIAL, GREEN) == "regression"


def test_partly_built_is_partial() -> None:
    assert _score("succeeded", GREEN, PARTIAL) == "partial"


def test_nothing_working_is_a_fail() -> None:
    assert _score("succeeded", GREEN, DEAD) == "fail"


def test_an_unrunnable_own_suite_does_not_mask_a_real_delivery() -> None:
    """No own-suite result at all (total 0) must not be reported as a regression."""
    assert _score("succeeded", NOT_RUN, GREEN) == "pass"


# -- tasks on disk -----------------------------------------------------------


def test_every_task_ships_a_request_hidden_tests_and_a_reference_solution() -> None:
    tasks = load_tasks()
    assert tasks, "no benchmark tasks found"
    for task in tasks:
        assert task.request.strip(), f"{task.id} has an empty request"
        assert task.hidden_test.is_file()
        assert task.solution is not None, f"{task.id} has no reference solution to prove fairness"


def test_unknown_task_ids_are_rejected_loudly() -> None:
    with pytest.raises(SystemExit, match="unknown task"):
        load_tasks(["no-such-task"])


# -- reporting ---------------------------------------------------------------


def test_the_report_states_the_budget_the_scores_were_measured_under(settings) -> None:
    settings = settings.model_copy(update={"max_tokens_per_run": 1_200_000})
    result = TaskResult(task_id="pagination", status="succeeded", score="pass",
                        hidden_tests=GREEN, own_tests=GREEN)

    report = to_markdown([result], settings)

    assert "1,200,000" in report, "a score is meaningless without the budget behind it"
    assert "pagination" in report and "PASS" in report


def test_the_report_says_what_concurrency_the_times_were_measured_at(settings) -> None:
    """Comparing a concurrent run's durations against a sequential one's would
    read queueing as a regression, so the pacing travels with the numbers."""
    result = TaskResult(task_id="pagination", status="succeeded", score="pass",
                        hidden_tests=GREEN, own_tests=GREEN)

    report = to_markdown([result], settings, concurrency=3)

    assert "concurrent runs: 3" in report
    assert "same concurrency" in report


def test_a_sequential_report_does_not_carry_the_concurrency_caveat(settings) -> None:
    result = TaskResult(task_id="pagination", status="succeeded", score="pass",
                        hidden_tests=GREEN, own_tests=GREEN)
    assert "same concurrency" not in to_markdown([result], settings)


# -- scheduling --------------------------------------------------------------


def make_task(task_id: str) -> Task:
    return Task(id=task_id, request="do a thing", hidden_test=Path("x"), solution=None)


def test_repetitions_are_interleaved_by_task() -> None:
    """A suite killed halfway must leave a smaller sample of every task rather
    than a full sample of some and none of the rest."""
    schedule = _schedule([make_task("a"), make_task("b")], repeat=3)

    assert [t.id for t, _r in schedule] == ["a", "a", "a", "b", "b", "b"]
    assert [r for _t, r in schedule] == [1, 2, 3, 1, 2, 3]


def test_a_single_repetition_schedules_each_task_once() -> None:
    assert len(_schedule([make_task("a"), make_task("b")], repeat=1)) == 2


# -- running concurrently ----------------------------------------------------


async def test_concurrent_tasks_each_get_their_own_checkout(tmp_path, settings) -> None:
    """Sharing one directory is what made the suite sequential; two tasks in it
    would edit the same files and reset each other mid-run."""
    template = tmp_path / "template"
    (template / "tests").mkdir(parents=True)
    (template / "app.py").write_text("x = 1\n", encoding="utf-8")

    bench = settings.model_copy(update={
        "workspace_root": tmp_path / "bench",
        "workspace_template": template,
        "database_path": tmp_path / "bench.db",
        "intake_enabled": False,
    })
    (tmp_path / "bench").mkdir()

    seen: list[Path] = []
    import harness

    async def spy(task, settings_, **kwargs):
        # `isolated=True` is what routes the task through its own worktree.
        assert kwargs.get("isolated") is True
        with harness._task_workspace(
            settings_, f"bench-{task.id}", task.request, isolated=True, keep=False
        ) as workspace:
            seen.append(workspace)
        return TaskResult(task_id=task.id, status="succeeded", score="pass")

    original, harness.run_task = harness.run_task, spy
    try:
        await run_suite([make_task("a"), make_task("b")], bench, concurrency=2)
    finally:
        harness.run_task = original

    assert len(seen) == 2
    assert seen[0] != seen[1], "each concurrent task needs its own working tree"


def test_failures_are_reported_with_their_output(settings) -> None:
    failing = TaskResult(
        task_id="jwt_auth", status="escalated", score="fail",
        hidden_tests=outcome(passed=0, failed=3, exit_code=1),
        own_tests=GREEN, error="token budget exhausted",
    )
    failing.hidden_tests.detail = "FAILED tests/test_acceptance_hidden.py::test_admin"

    report = to_markdown([failing], settings)

    assert "## Failures" in report
    assert "token budget exhausted" in report
    assert "test_admin" in report


# -- provenance --------------------------------------------------------------


def test_results_record_the_code_that_produced_them(settings, tmp_path) -> None:
    """A measurement was once read as having run with a fix committed while it
    was already in flight: the process had loaded the old modules at import,
    and nothing in the file said so. Reconstructing that from timestamps took
    an hour; recording it costs a subprocess call."""
    import harness

    payload_dir = tmp_path / "results"
    original, harness.RESULTS_DIR = harness.RESULTS_DIR, payload_dir
    try:
        json_path, _ = harness.write_results([], settings)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    finally:
        harness.RESULTS_DIR = original

    version = payload["code_version"]
    assert set(version) == {"commit", "dirty"}
    assert version["commit"], "a result with no provenance is a result nobody can reproduce"


def test_uncommitted_edits_are_reported_not_hidden() -> None:
    """The hash alone cannot reproduce a run taken over local edits."""
    import harness

    version = harness._code_version()
    assert version["dirty"] in (True, False, None)


# --------------------------------------------------------------------------
# an unreachable server is not a result
# --------------------------------------------------------------------------


@pytest.mark.parametrize("error", [
    "EndpointUnavailable: http://host:30000/v1 is unreachable: Server disconnected",
    "AllEndpointsDown: no endpoint answered",
])
def test_infrastructure_failures_are_recognised(error):
    assert is_infrastructure_failure(error)


@pytest.mark.parametrize("error", [
    "",
    "Escalation: could not put run 1a2b3c on its own branch",
    "token budget exhausted (455356/400000)",
    # The words appear, but as prose inside another failure — the classifier
    # keys on the exception name, which is the first token before the colon.
    "Escalation: gave up after EndpointUnavailable: retried three times",
])
def test_ordinary_failures_are_left_alone(error):
    assert not is_infrastructure_failure(error)


def test_a_task_nobody_measured_is_not_counted_as_a_clean_sweep(tmp_path):
    """`passes == n` is true of zero and zero. It must also have run."""
    results = [TaskResult(task_id="tags", status="failed", score="unusable", error="AllEndpointsDown: x")]
    report = to_markdown(results, benchmark_settings())

    assert "tasks passing every repetition: **0/1**" in report
    assert "never ran" in report
    assert "never reached a model" in report
