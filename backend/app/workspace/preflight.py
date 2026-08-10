"""Preflight checks for working on a repository you care about.

The demo workspace is disposable — it is copied from a template and thrown
away. A real project is not, so pointing the crew at one has to be deliberate
and has to refuse the situations where a run would be hard to undo:

* not a git repository — there would be no way back;
* uncommitted work — the agents' changes would mix with the user's, and the
  run's diff would no longer be the run's;
* a detached HEAD — the branch the run creates would dangle;
* the crew's own source tree — an agent editing the orchestrator mid-run.

These are checked before the run starts, not discovered halfway through.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import REPO_ROOT, Settings
from .sandbox import Sandbox, SandboxViolation


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    message: str
    remedy: str = ""
    blocking: bool = True

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "code": self.code,
            "message": self.message,
            "remedy": self.remedy,
            "blocking": self.blocking,
        }


class PreflightFailed(RuntimeError):
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__("; ".join(i.message for i in issues))


def _is_own_source(root: Path) -> bool:
    """True when the workspace would contain (or be) this project's own code."""
    root = root.resolve()
    repo = REPO_ROOT.resolve()
    if root == repo or repo.is_relative_to(root):
        return True
    return (root / "backend" / "app" / "orchestrator" / "engine.py").is_file()


def check(settings: Settings) -> list[Issue]:
    """Return every reason this workspace is not safe to run against.

    An empty list means go. Managed (template-provisioned) workspaces are
    disposable, so only the self-modification guard applies to them.
    """
    issues: list[Issue] = []
    root = settings.workspace_root

    if _is_own_source(root):
        issues.append(Issue(
            code="self_modification",
            message="the workspace contains this project's own source",
            remedy="point WORKSPACE_ROOT somewhere else — an agent must not edit the orchestrator it is running on",
        ))
        return issues  # nothing else matters if this is true

    managed = settings.workspace_template is not None
    if managed:
        return issues

    # --- bring-your-own-project mode ---------------------------------------
    if not settings.allow_external_workspace:
        issues.append(Issue(
            code="not_opted_in",
            message="working on an external project requires an explicit opt-in",
            remedy="set ALLOW_EXTERNAL_WORKSPACE=true in .env once you understand the crew will branch and commit in that repository",
        ))

    if not root.exists():
        issues.append(Issue(
            code="missing",
            message=f"{root} does not exist",
            remedy="create it, or point WORKSPACE_ROOT at an existing project",
        ))
        return issues

    try:
        sandbox = Sandbox(root)
    except SandboxViolation as exc:
        issues.append(Issue(code="unusable", message=str(exc)))
        return issues

    if not sandbox.is_git_repo():
        issues.append(Issue(
            code="not_a_repo",
            message=f"{root} is not a git repository",
            remedy="run `git init && git commit` there first — the crew will not initialise a repository it did not create",
        ))
        return issues  # the remaining checks all need a repository

    if not sandbox.is_clean():
        issues.append(Issue(
            code="dirty_tree",
            message="the working tree has uncommitted changes",
            remedy="commit or stash them, so the run's diff contains only the run's work",
        ))

    branch = sandbox.current_branch()
    if branch == "HEAD":
        issues.append(Issue(
            code="detached_head",
            message="HEAD is detached",
            remedy="check out a branch — the run branches from HEAD and would otherwise dangle",
        ))

    if not any((root / name).exists() for name in ("tests", "test", "spec", "__tests__")):
        issues.append(Issue(
            code="no_tests",
            message="no test directory found",
            remedy="QA can still read the diff, but it will have nothing to run — expect weaker verdicts",
            blocking=False,
        ))

    return issues


def assert_ready(settings: Settings) -> None:
    blocking = [issue for issue in check(settings) if issue.blocking]
    if blocking:
        raise PreflightFailed(blocking)
