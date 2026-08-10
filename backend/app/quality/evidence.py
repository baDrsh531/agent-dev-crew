"""Machine-gathered evidence for the QA agent.

A verdict is only worth as much as what it is grounded in. Left to itself an
agent decides which checks to run, and a run where it forgot the secret scan
looks exactly like one where the scan came back clean.

So the checks are run in code, always, in a fixed order, and their results are
handed to QA as facts it must reconcile with — not as tools it may choose to
call. The division is deliberate: **code gathers evidence, the model judges
it**. A regex cannot tell whether a hardcoded string is a real credential or a
test fixture; only the model can. But only code can guarantee it looked.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass, field
from typing import Any

from ..tools.base import ToolContext
from ..tools.shell import COMMAND_TIMEOUT_SECONDS, resolve_interpreter_dir, run_suite, vet
from ..workspace.sandbox import Sandbox

MAX_DETAIL_CHARS = 1_500

# Patterns worth stopping a release for. Deliberately narrow: a scanner that
# cries wolf is one QA learns to wave through, which is worse than no scanner.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "hardcoded credential",
        re.compile(
            r"""(?ix)
            \b(?:secret|password|passwd|api[_-]?key|token)\b   # a name that claims to be one
            \s*[:=]\s*
            ['"][^'"\s]{8,}['"]                                # assigned a non-trivial literal
            """
        ),
    ),
]

# Assignments that are obviously not credentials, however they are named.
SECRET_ALLOWLIST = re.compile(
    r"""(?ix)
    (?: os\.environ | getenv | os\.getenv | settings\. | config\. | \{\{ | \$\{ )
    | ['"](?: changeme | placeholder | example | dummy | xxx+ | \.\.\. )['"]
    """
)


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "passed": self.passed,
            "detail": self.detail[:MAX_DETAIL_CHARS], "skipped": self.skipped,
        }


@dataclass(slots=True)
class Evidence:
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and not c.skipped]

    def as_dict(self) -> dict[str, Any]:
        return {
            "checks": [c.as_dict() for c in self.checks],
            "failed": [c.name for c in self.failures],
        }

    def render(self) -> str:
        """The block handed to QA. Skips are stated, never silently omitted."""
        lines = []
        for check in self.checks:
            mark = "SKIPPED" if check.skipped else ("PASS" if check.passed else "FAIL")
            lines.append(f"[{mark}] {check.name}: {check.detail[:MAX_DETAIL_CHARS]}")
        return "\n".join(lines) or "no checks were run"


# --------------------------------------------------------------------------
# individual checks
# --------------------------------------------------------------------------


def scan_for_secrets(diff: str) -> Check:
    """Look for credentials in what this run added. Added lines only.

    Scanning the whole tree would report every pre-existing finding on every
    run, which is how a scanner becomes noise. This one only ever reports what
    the crew introduced.
    """
    added = [
        line[1:] for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    hits: list[str] = []
    for line in added:
        if SECRET_ALLOWLIST.search(line):
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                hits.append(f"{label}: {line.strip()[:120]}")
                break

    if not added:
        return Check("secret scan", True, "no lines were added", skipped=False)
    if hits:
        return Check(
            "secret scan", False,
            f"{len(hits)} suspicious value(s) in added lines:\n" + "\n".join(hits[:10]),
        )
    return Check("secret scan", True, f"{len(added)} added lines, nothing matched")


def measure_diff(diff: str) -> Check:
    """Size is not a defect, but a plan-sized change delivered as a rewrite is."""
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    files = sum(1 for line in diff.splitlines() if line.startswith("diff --git"))
    return Check(
        "change size", True,
        f"{files} file(s), +{added}/-{removed} lines",
    )


async def _run_tool(ctx: ToolContext, command: str, name: str, missing_hint: str) -> Check:
    argv, error = vet(command, resolve_interpreter_dir(ctx.sandbox.root))
    if error:
        return Check(name, True, f"not run: {error}", skipped=True)
    if not shutil.which(argv[0]) and not argv[0].endswith((".exe", ".cmd")):
        return Check(name, True, f"not installed ({missing_hint})", skipped=True)

    try:
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=str(ctx.sandbox.root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
            stdout, _ = await process.communicate()
    except (OSError, asyncio.TimeoutError) as exc:
        return Check(name, True, f"not run: {type(exc).__name__}", skipped=True)

    output = stdout.decode("utf-8", errors="replace").strip()
    return Check(name, (process.returncode or 0) == 0, output or "clean")


async def run_tests(ctx: ToolContext, baseline: str) -> Check:
    result = await run_suite(ctx)
    detail = result.content
    if baseline:
        detail = f"{detail}\n--- before the change ---\n{baseline[:600]}"
    return Check("test suite", not result.is_error, detail)


async def collect(sandbox: Sandbox, ctx: ToolContext, *, diff: str, baseline: str) -> Evidence:
    """Run every check, in a fixed order, whatever the agent would have chosen."""
    evidence = Evidence()
    evidence.checks.append(await run_tests(ctx, baseline))
    evidence.checks.append(scan_for_secrets(diff))
    evidence.checks.append(
        await _run_tool(ctx, "ruff check .", "lint (ruff)", "pip install ruff")
    )
    evidence.checks.append(measure_diff(diff))
    return evidence
