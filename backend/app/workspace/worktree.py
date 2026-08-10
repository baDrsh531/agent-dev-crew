"""One git worktree per run.

Until now every run shared a single directory, so runs had to be sequential and
"undo this run" meant surgery on a branch other runs might also be standing on.
A worktree gives each run its own checkout of the same repository: separate
files, separate branch, shared object store.

Three things fall out of that, and they are the reason this exists rather than
copying the directory again:

* **Concurrency** — two runs cannot collide, because they do not share a
  working tree.
* **Rollback is a delete** — discarding a run is removing its directory and its
  branch. Nothing has to be untangled from anyone else's work.
* **Provisioning is nearly free** — a worktree is a checkout, not a copy of the
  history, so starting a run no longer copies the whole template.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .provision import remove_tree

log = logging.getLogger("crew.worktree")

BASELINE_MESSAGE = "baseline before agent runs"


class WorktreeError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    # Fixed executable, no shell.
    return subprocess.run(  # noqa: S603
        ["git", "-c", "user.email=crew@local", "-c", "user.name=Agent Crew", *args],
        cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
    )


def _directory_name(run_id: str) -> str:
    """A filesystem-safe name that is unique per run id, never truncated."""
    return re.sub(r"[^A-Za-z0-9_.-]", "-", run_id) or "run"


def branch_name(run_id: str, request: str) -> str:
    """The readable name a run would like. Not guaranteed free — see `create`."""
    slug = re.sub(r"[^a-z0-9]+", "-", request.lower()).strip("-")[:40].rstrip("-")
    return f"agent/{run_id[:8]}-{slug or 'task'}"


def _free_branch(base_repo: Path, preferred: str) -> str:
    """`preferred`, or the first free variant of it.

    The readable name is only a prefix of the run id plus a slug of the
    request, and that is not unique: two concurrent benchmark repetitions of
    one task want exactly the same name. Taking it would either fail or, worse,
    hand a second run the branch a first one is still committing to.
    """
    existing = {
        line.strip().lstrip("* ").strip()
        for line in _git(base_repo, "branch", "--list", "--format=%(refname:short)").stdout.splitlines()
    }
    if preferred not in existing:
        return preferred
    for suffix in range(2, 1000):
        candidate = f"{preferred}-{suffix}"
        if candidate not in existing:
            return candidate
    raise WorktreeError(f"could not find a free branch name near {preferred}")


def ensure_base_repo(root: Path) -> str:
    """Make `root` a git repository with at least one commit, and return HEAD.

    A worktree can only be branched from a commit, so an empty repository is
    not a valid base. This is idempotent: an existing repository is left alone.
    """
    root = Path(root)
    if not root.is_dir():
        raise WorktreeError(f"workspace root does not exist: {root}")

    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        if _git(root, "init").returncode != 0:
            raise WorktreeError(f"could not initialise a repository in {root}")

    if _git(root, "rev-parse", "HEAD").returncode != 0:
        _git(root, "add", "-A")
        commit = _git(root, "commit", "-m", BASELINE_MESSAGE, "--allow-empty")
        if commit.returncode != 0:
            raise WorktreeError(f"could not create the baseline commit: {commit.stderr.strip()}")

    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise WorktreeError(f"repository in {root} has no HEAD")
    return head.stdout.strip()


@dataclass(slots=True)
class Worktree:
    """A run's private checkout."""

    path: Path
    branch: str
    base_commit: str
    base_repo: Path

    def remove(self) -> None:
        """Delete the checkout and the branch. This is what "undo" means."""
        result = _git(self.base_repo, "worktree", "remove", str(self.path), "--force")
        if result.returncode != 0 and self.path.exists():
            # Git refuses when the directory is already gone or locked; the
            # files still have to go, and `prune` then tidies the metadata.
            remove_tree(self.path)
            _git(self.base_repo, "worktree", "prune")
        _git(self.base_repo, "branch", "-D", self.branch)


def create(base_repo: Path, run_id: str, request: str) -> Worktree:
    """Branch a fresh worktree for one run."""
    base_repo = Path(base_repo)
    base_commit = ensure_base_repo(base_repo)

    # Worktrees live outside the repository: nesting one inside its own base
    # would put a run's files into the next run's diff.
    #
    # The directory is named after the *whole* run id, not a readable prefix of
    # it: two concurrent benchmark runs of the same task share a prefix, and a
    # truncated name would give them the same directory — each deleting the
    # other's work. The branch carries the readable name instead.
    path = base_repo.parent / "worktrees" / _directory_name(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        remove_tree(path)
    # Deleting the directory does not deregister it: git still knows the path
    # and refuses to reuse it as "missing but already registered". Pruning is
    # also what recovers a worktree whose directory was removed by hand.
    prune(base_repo)

    branch = _free_branch(base_repo, branch_name(run_id, request))
    result = _git(base_repo, "worktree", "add", "-b", branch, str(path), base_commit)
    if result.returncode != 0:
        raise WorktreeError(
            f"could not create a worktree for run {run_id}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    log.info("run %s works in %s on %s", run_id[:8], path, branch)
    return Worktree(path=path, branch=branch, base_commit=base_commit, base_repo=base_repo)


def list_worktrees(base_repo: Path) -> list[str]:
    result = _git(Path(base_repo), "worktree", "list", "--porcelain")
    return [
        line.split(" ", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def prune(base_repo: Path) -> None:
    """Drop metadata for worktrees whose directories are gone."""
    _git(Path(base_repo), "worktree", "prune")
