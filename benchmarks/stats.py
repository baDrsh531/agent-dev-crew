"""Aggregating repeated runs, and refusing to over-read the result.

A single run per task cannot separate a real effect from noise: on this suite
`pagination` scored 11/11, then 3/11, then 11/11 on identical code with
identical settings. So the harness repeats each task and reports a distribution
rather than a number.

The comparison rule below is deliberately conservative and deliberately
mechanical. It is easy, when you have just spent an afternoon on a change, to
look at 181 → 240 and narrate a reason. Encoding the rule in the tool means the
tool says "indistinguishable" whether or not that is the answer you wanted.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


@dataclass(slots=True)
class Distribution:
    """A metric measured several times."""

    values: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def median(self) -> float:
        return statistics.median(self.values) if self.values else 0.0

    @property
    def low(self) -> float:
        return min(self.values) if self.values else 0.0

    @property
    def high(self) -> float:
        return max(self.values) if self.values else 0.0

    @property
    def spread(self) -> float:
        """How wide the range is, relative to the median. The honest headline."""
        return (self.high - self.low) / self.median if self.median else 0.0

    def render(self, unit: str = "") -> str:
        if self.n == 0:
            return "—"
        if self.n == 1:
            return f"{self.median:,.0f}{unit}"
        return f"{self.median:,.0f}{unit} ({self.low:,.0f}–{self.high:,.0f})"

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n, "median": self.median, "low": self.low, "high": self.high,
            "spread": round(self.spread, 3), "values": self.values,
        }


@dataclass(slots=True)
class TaskAggregate:
    task_id: str
    scores: list[str] = field(default_factory=list)
    tokens: Distribution = field(default_factory=Distribution)
    tool_calls: Distribution = field(default_factory=Distribution)
    duration_s: Distribution = field(default_factory=Distribution)
    hidden_passed: Distribution = field(default_factory=Distribution)
    hidden_total: int = 0
    #: Repetitions that never reached a model — counted, never averaged in.
    unusable: int = 0

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def passes(self) -> int:
        return sum(1 for s in self.scores if s == "pass")

    @property
    def pass_rate(self) -> float:
        return self.passes / self.n if self.n else 0.0

    @property
    def is_flaky(self) -> bool:
        """Different outcomes from identical inputs. Worth knowing before tuning."""
        return len(set(self.scores)) > 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "runs": self.n,
            "scores": self.scores,
            "passes": self.passes,
            "pass_rate": round(self.pass_rate, 3),
            "flaky": self.is_flaky,
            "unusable": self.unusable,
            "tokens": self.tokens.as_dict(),
            "tool_calls": self.tool_calls.as_dict(),
            "duration_s": self.duration_s.as_dict(),
            "hidden_passed": self.hidden_passed.as_dict(),
            "hidden_total": self.hidden_total,
        }


def aggregate(results: Iterable[Any]) -> list[TaskAggregate]:
    """Group repeated TaskResults by task."""
    by_task: dict[str, TaskAggregate] = {}
    for result in results:
        entry = by_task.setdefault(result.task_id, TaskAggregate(task_id=result.task_id))
        if getattr(result, "score", "") == "unusable":
            # A repetition that never reached a model says nothing about the
            # crew. Averaging it in produced a median of 135,634 tokens over a
            # range of 1,713–231,852 and called the task flaky; the task was
            # fine, the server was down. Counted so the report can say how many
            # measurements are actually behind each row.
            entry.unusable += 1
            continue
        entry.scores.append(result.score)
        entry.tokens.values.append(result.tokens)
        entry.tool_calls.values.append(result.tool_calls)
        entry.duration_s.values.append(result.duration_s)
        entry.hidden_passed.values.append(result.hidden_tests.passed)
        entry.hidden_total = max(entry.hidden_total, result.hidden_tests.total)
    return [by_task[key] for key in sorted(by_task)]


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------

INDISTINGUISHABLE = "indistinguishable"


def compare_metric(before: Distribution, after: Distribution) -> dict[str, Any]:
    """Judge whether two measurements actually differ.

    The rule: the two observed ranges must not overlap. With three or four
    repetitions there is no honest way to claim a small difference — a
    non-overlap is the weakest claim that still means something, and anything
    stronger would be dressing up noise as a finding.
    """
    if before.n == 0 or after.n == 0:
        return {"verdict": "no data", "change_pct": None}

    change = (
        (after.median - before.median) / before.median * 100 if before.median else 0.0
    )
    single_sample = before.n < 2 or after.n < 2
    overlapping = not (after.low > before.high or after.high < before.low)

    if single_sample:
        verdict = "unrepeated"          # one run each: a difference cannot be read
    elif overlapping:
        verdict = INDISTINGUISHABLE
    elif change < 0:
        verdict = "better"
    else:
        verdict = "worse"

    return {
        "verdict": verdict,
        "change_pct": round(change, 1),
        "before": before.render(),
        "after": after.render(),
    }


def compare(
    before: Sequence[TaskAggregate], after: Sequence[TaskAggregate]
) -> dict[str, Any]:
    """Compare two aggregated suites, per task and overall."""
    before_by_id = {a.task_id: a for a in before}
    after_by_id = {a.task_id: a for a in after}
    shared = sorted(set(before_by_id) & set(after_by_id))

    per_task = {
        task_id: {
            "tokens": compare_metric(before_by_id[task_id].tokens, after_by_id[task_id].tokens),
            "tool_calls": compare_metric(
                before_by_id[task_id].tool_calls, after_by_id[task_id].tool_calls
            ),
            "pass_rate": {
                "before": before_by_id[task_id].pass_rate,
                "after": after_by_id[task_id].pass_rate,
            },
        }
        for task_id in shared
    }

    verdicts = [
        per_task[t][metric]["verdict"] for t in shared for metric in ("tokens", "tool_calls")
    ]
    if not verdicts:
        overall = "no comparable tasks"
    elif all(v in {INDISTINGUISHABLE, "unrepeated"} for v in verdicts):
        overall = INDISTINGUISHABLE
    elif "worse" in verdicts and "better" in verdicts:
        overall = "mixed"
    elif "worse" in verdicts:
        overall = "worse"
    else:
        overall = "better"

    return {"tasks": per_task, "overall": overall, "compared": shared}


def render_comparison(comparison: dict[str, Any]) -> str:
    lines = [
        "# Comparison",
        "",
        f"Overall: **{comparison['overall']}**",
        "",
        "A difference is only called real when the two observed ranges do not",
        "overlap. With a handful of repetitions, anything weaker is noise.",
        "",
        "| task | metric | before | after | change | verdict |",
        "|---|---|---|---|---:|---|",
    ]
    for task_id, metrics in comparison["tasks"].items():
        for metric in ("tokens", "tool_calls"):
            entry = metrics[metric]
            change = f"{entry['change_pct']:+.0f}%" if entry["change_pct"] is not None else "—"
            lines.append(
                f"| `{task_id}` | {metric} | {entry.get('before', '—')} | "
                f"{entry.get('after', '—')} | {change} | {entry['verdict']} |"
            )
    return "\n".join(lines)
