"""Workspace confinement.

Every path an agent supplies is untrusted model output. Nothing in this system
touches the filesystem without going through `Sandbox.resolve()` first, which
canonicalises the path and refuses anything that escapes the workspace root —
`..`, absolute paths, symlinks pointing outside, drive-letter tricks on Windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

MAX_READ_BYTES = 400_000
MAX_WRITE_BYTES = 2_000_000

# Directories an agent has no business reading or writing, even inside the root.
BLOCKED_SEGMENTS = frozenset({".git", ".env", "node_modules", "__pycache__", ".venv"})


class SandboxViolation(Exception):
    """Raised when a path or command would leave the confined workspace."""


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        if not self.root.exists():
            raise SandboxViolation(f"workspace root does not exist: {self.root}")
        if not self.root.is_dir():
            raise SandboxViolation(f"workspace root is not a directory: {self.root}")

    # -- paths ------------------------------------------------------------

    def resolve(self, relative: str, *, allow_blocked: bool = False) -> Path:
        """Canonicalise a model-supplied path, or refuse it.

        `allow_blocked` exists solely for our own git plumbing, which legitimately
        needs `.git`. Tools never set it.
        """
        if relative is None or not str(relative).strip():
            raise SandboxViolation("empty path")

        raw = str(relative).replace("\\", "/").strip()
        if raw.startswith("~"):
            raise SandboxViolation(f"home-relative path refused: {relative}")

        candidate = Path(raw)
        if candidate.is_absolute() or (os.name == "nt" and candidate.drive):
            # Accept an absolute path only if it already sits inside the root.
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()

        try:
            rel = resolved.relative_to(self.root)
        except ValueError as exc:
            raise SandboxViolation(
                f"path escapes the workspace: {relative} -> {resolved}"
            ) from exc

        if not allow_blocked:
            blocked = BLOCKED_SEGMENTS.intersection(rel.parts)
            if blocked:
                raise SandboxViolation(
                    f"path touches a protected location {sorted(blocked)}: {relative}"
                )
        return resolved

    def relative(self, path: Path) -> str:
        """Workspace-relative, forward-slashed — the only form shown to agents."""
        return Path(path).resolve().relative_to(self.root).as_posix()

    # -- reads ------------------------------------------------------------

    def read_text(self, relative: str) -> str:
        path = self.resolve(relative)
        if not path.exists():
            raise SandboxViolation(f"file not found: {relative}")
        if not path.is_file():
            raise SandboxViolation(f"not a file: {relative}")
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            raise SandboxViolation(
                f"file too large to read ({size} bytes > {MAX_READ_BYTES}): {relative}"
            )
        return path.read_text(encoding="utf-8", errors="replace")

    def list_files(self, pattern: str = "**/*", limit: int = 500) -> list[str]:
        results: list[str] = []
        for path in sorted(self.root.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            if BLOCKED_SEGMENTS.intersection(rel.parts):
                continue
            results.append(rel.as_posix())
            if len(results) >= limit:
                break
        return results

    # -- writes -----------------------------------------------------------

    def write_text(self, relative: str, content: str) -> Path:
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise SandboxViolation(f"refusing to write more than {MAX_WRITE_BYTES} bytes")
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def delete(self, relative: str) -> Path:
        path = self.resolve(relative)
        if not path.exists():
            raise SandboxViolation(f"file not found: {relative}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return path

    # -- git --------------------------------------------------------------

    def git(self, *args: str, check: bool = False, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        """Run git against the workspace. Arguments are never shell-interpreted."""
        return subprocess.run(  # noqa: S603 - fixed executable, no shell
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    def is_git_repo(self) -> bool:
        """True when this directory is *inside* a repository — possibly a parent's."""
        result = self.git("rev-parse", "--is-inside-work-tree")
        return result.returncode == 0 and result.stdout.strip() == "true"

    def owns_git_repo(self) -> bool:
        """True only when the repository's root *is* this directory.

        `is_git_repo()` answers about the nearest repository up the tree, which
        is the wrong question when deciding whether to create one: a workspace
        nested inside another checkout would adopt it and start branching and
        committing in someone else's history.
        """
        result = self.git("rev-parse", "--show-toplevel")
        if result.returncode != 0:
            return False
        try:
            return Path(result.stdout.strip()).resolve() == self.root.resolve()
        except OSError:
            return False

    def free_branch(self, preferred: str) -> str:
        """`preferred`, or the first unused variant of it.

        The readable name is a prefix of the run id plus a slug of the request,
        which is identical for every repetition of one benchmark task. Two runs
        wanting one branch is not a conflict to report — it is a name to pick
        again.
        """
        listed = self.git("branch", "--list", "--format=%(refname:short)")
        taken = {line.strip() for line in listed.stdout.splitlines() if line.strip()}
        if preferred not in taken:
            return preferred
        for suffix in range(2, 1000):
            if f"{preferred}-{suffix}" not in taken:
                return f"{preferred}-{suffix}"
        raise SandboxViolation(f"no free branch name near {preferred}")

    def current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def is_clean(self) -> bool:
        result = self.git("status", "--porcelain")
        return result.returncode == 0 and not result.stdout.strip()

    def diff(self, *, staged: bool = False) -> str:
        args = ["diff", "--staged"] if staged else ["diff"]
        return self.git(*args).stdout
