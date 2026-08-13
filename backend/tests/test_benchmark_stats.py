"""Aggregation and the comparison rule.

The rule exists to be applied when it is inconvenient, so it is tested with
cases where a large-looking change must still be reported as noise.
"""

from __future__ import annotations

import sys
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from harness import SuiteOutcome, TaskResult  # noqa: E402
from stats import (  # noqa: E402
    Distribution, aggregate, compare, compare_metric, render_comparison,
)


def result(task_id: str, score: str, tokens: int, tools: int, hidden=(5, 5)) -> TaskResult:
    passed, total = hidden
    return TaskResult(
        task_id=task_id, status="succeeded", score=score,
        tokens=tokens, tool_calls=tools, duration_s=100.0,
        hidden_tests=SuiteOutcome(passed=passed, failed=total - passed, exit_code=0),
        own_tests=SuiteOutcome(passed=7, exit_code=0),
    )


# -- distributions -----------------------------------------------------------


def test_a_single_value_renders_without_a_fake_range() -> None:
    assert Distribution([500]).render() == "500"


def test_repeated_values_render_median_and_range() -> None:
    assert Distribution([100, 500, 300]).render() == "300 (100–500)"


def test_spread_is_relative_to_the_median() -> None:
    assert Distribution([90, 100, 110]).spread == 0.2
    assert Distribution([]).spread == 0.0


# -- aggregation -------------------------------------------------------------


def test_repetitions_of_a_task_collapse_into_one_row() -> None:
    aggregates = aggregate([
        result("pagination", "pass", 100, 10),
        result("pagination", "pass", 200, 20),
        result("search", "fail", 300, 30),
    ])
    assert [a.task_id for a in aggregates] == ["pagination", "search"]
    assert aggregates[0].n == 2
    assert aggregates[0].tokens.median == 150


def test_a_task_with_different_outcomes_is_flagged_flaky() -> None:
    """Identical inputs, different results — worth knowing before tuning."""
    aggregates = aggregate([
        result("pagination", "pass", 100, 10),
        result("pagination", "fail", 100, 10),
        result("pagination", "pass", 100, 10),
    ])
    assert aggregates[0].is_flaky is True
    assert aggregates[0].passes == 2
    assert aggregates[0].pass_rate == 2 / 3


def test_a_consistent_task_is_not_flagged() -> None:
    aggregates = aggregate([result("x", "pass", 1, 1), result("x", "pass", 2, 2)])
    assert aggregates[0].is_flaky is False


# -- the comparison rule -----------------------------------------------------


def test_one_run_each_cannot_be_read_however_large_the_change() -> None:
    """The case this rule exists for: a 300% shift measured once is not a finding."""
    verdict = compare_metric(Distribution([198_393]), Distribution([827_396]))
    assert verdict["verdict"] == "unrepeated"
    assert verdict["change_pct"] == 317.0


def test_overlapping_ranges_are_indistinguishable() -> None:
    before = Distribution([100, 200, 300])
    after = Distribution([150, 250, 350])
    assert compare_metric(before, after)["verdict"] == "indistinguishable"


def test_a_clean_separation_downwards_is_better() -> None:
    before = Distribution([300, 320, 340])
    after = Distribution([100, 110, 120])
    verdict = compare_metric(before, after)
    assert verdict["verdict"] == "better"
    assert verdict["change_pct"] < 0


def test_a_clean_separation_upwards_is_worse() -> None:
    before = Distribution([100, 110, 120])
    after = Distribution([300, 320, 340])
    assert compare_metric(before, after)["verdict"] == "worse"


def test_a_single_outlier_that_overlaps_blocks_the_claim() -> None:
    """Two of three runs improving is not enough when the third overlaps."""
    before = Distribution([300, 310, 320])
    after = Distribution([100, 110, 305])
    assert compare_metric(before, after)["verdict"] == "indistinguishable"


def test_no_data_is_reported_as_such() -> None:
    assert compare_metric(Distribution([]), Distribution([1, 2]))["verdict"] == "no data"


# -- suite comparison --------------------------------------------------------


def build(scores_and_tokens, task="t") -> list:
    return aggregate([result(task, s, tok, tok // 10) for s, tok in scores_and_tokens])


def test_a_suite_where_nothing_separates_is_indistinguishable() -> None:
    before = build([("pass", 100), ("pass", 200), ("pass", 300)])
    after = build([("pass", 150), ("pass", 250), ("pass", 280)])
    assert compare(before, after)["overall"] == "indistinguishable"


def test_a_suite_that_moved_cleanly_says_so() -> None:
    before = build([("pass", 300), ("pass", 310), ("pass", 320)])
    after = build([("pass", 100), ("pass", 110), ("pass", 120)])
    assert compare(before, after)["overall"] == "better"


def test_tasks_missing_from_one_side_are_skipped_not_guessed() -> None:
    before = build([("pass", 100), ("pass", 110)], task="a")
    after = build([("pass", 100), ("pass", 110)], task="b")
    comparison = compare(before, after)
    assert comparison["compared"] == []
    assert comparison["overall"] == "no comparable tasks"


def test_the_report_states_the_rule_it_applied() -> None:
    report = render_comparison(compare(
        build([("pass", 100), ("pass", 110)]),
        build([("pass", 300), ("pass", 310)]),
    ))
    assert "do not" in report and "overlap" in report
    assert "worse" in report


# --------------------------------------------------------------------------
# runs that never reached a model
# --------------------------------------------------------------------------
#
# From a real pass: the model server went away mid-suite, two of three
# `tag_validation` repetitions never called it, and the report said
# `1/3 ⚠︎ flaky`, median 135,634 tokens over a range of 1,713–231,852. Every
# one of those numbers was about the network, and every one of them read as an
# accusation against the crew.


def test_a_run_that_never_reached_a_model_is_not_averaged_in():
    aggregates = aggregate([
        result("tags", "pass", 230_000, 27),
        result("tags", "unusable", 1_713, 4),
        result("tags", "unusable", 135_634, 22),
    ])
    tags = aggregates[0]

    assert tags.unusable == 2
    assert tags.n == 1, "only the repetition that ran counts as a repetition"
    assert tags.tokens.values == [230_000]
    assert tags.tokens.low == tags.tokens.high == 230_000
    assert not tags.is_flaky, "one outcome cannot disagree with itself"


def test_excluding_them_makes_the_comparison_admit_it_has_one_sample():
    """The safe direction: fewer measurements must weaken the verdict.

    Before, the dead runs padded the sample and let a confident verdict rest
    on a range that infrastructure had widened.
    """
    before = aggregate([result("tags", "pass", 100_000, 20)])
    after = aggregate([
        result("tags", "pass", 400_000, 40),
        result("tags", "unusable", 0, 0),
        result("tags", "unusable", 0, 0),
    ])
    verdict = compare_metric(before[0].tokens, after[0].tokens)

    assert verdict["verdict"] == "unrepeated"
    assert verdict["change_pct"] == 300.0, "the number is still reported, just not believed"


def test_a_task_where_nothing_ran_reports_no_data_rather_than_a_verdict():
    before = aggregate([result("tags", "pass", 100_000, 20)])
    after = aggregate([result("tags", "unusable", 0, 0)])

    assert after[0].n == 0
    assert compare_metric(before[0].tokens, after[0].tokens)["verdict"] == "no data"
