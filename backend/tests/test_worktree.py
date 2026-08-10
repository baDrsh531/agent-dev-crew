"""Per-run worktrees: isolation, concurrency, and rollback as a delete."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.workspace.worktree import (
    WorktreeError, branch_name, create, ensure_base_repo, list_worktrees, prune,
)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, capture_output=True, text=True, check=False,
    ).stdout.strip()


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")
    return root


# -- the base repository -----------------------------------------------------


def test_a_plain_directory_becomes_a_repository_with_a_commit(base: Path) -> None:
    """A worktree can only branch from a commit, so an empty repo is not a base."""
    head = ensure_base_repo(base)
    assert len(head) == 40
    assert (base / ".git").exists()


def test_preparing_the_base_twice_changes_nothing(base: Path) -> None:
    first = ensure_base_repo(base)
    assert ensure_base_repo(base) == first


def test_an_existing_repository_keeps_its_history(base: Path) -> None:
    git(base, "init")
    git(base, "add", "-A")
    git(base, "commit", "-m", "their own commit")
    existing = git(base, "rev-parse", "HEAD")

    assert ensure_base_repo(base) == existing


def test_a_missing_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorktreeError, match="does not exist"):
        ensure_base_repo(tmp_path / "nowhere")


# -- creating a worktree -----------------------------------------------------


def test_a_run_gets_its_own_checkout(base: Path) -> None:
    worktree = create(base, "run1234abcd", "Add pagination")

    assert worktree.path.is_dir()
    assert (worktree.path / "app" / "main.py").read_text(encoding="utf-8") == "x = 1\n"
    assert worktree.branch.startswith("agent/run1234")


def test_the_checkout_lives_outside_the_base_repository(base: Path) -> None:
    """Nesting it would put one run's files into the next run's diff."""
    worktree = create(base, "run1234abcd", "Add pagination")
    assert not worktree.path.resolve().is_relative_to(base.resolve())


def test_two_runs_do_not_share_a_working_tree(base: Path) -> None:
    """This is what makes concurrent runs possible at all."""
    one = create(base, "aaaaaaaaaaaa", "First task")
    two = create(base, "bbbbbbbbbbbb", "Second task")

    (one.path / "app" / "main.py").write_text("first\n", encoding="utf-8")
    (two.path / "app" / "main.py").write_text("second\n", encoding="utf-8")

    assert (one.path / "app" / "main.py").read_text(encoding="utf-8") == "first\n"
    assert (two.path / "app" / "main.py").read_text(encoding="utf-8") == "second\n"
    assert one.branch != two.branch


def test_each_run_starts_from_the_same_pristine_state(base: Path) -> None:
    """A worktree is branched from the base commit, so an earlier run's edits
    cannot leak into a later one — which is what benchmarks depend on."""
    one = create(base, "aaaaaaaaaaaa", "First task")
    (one.path / "app" / "main.py").write_text("changed by the first run\n", encoding="utf-8")
    git(one.path, "add", "-A")
    git(one.path, "commit", "-m", "first run's work")

    two = create(base, "bbbbbbbbbbbb", "Second task")
    assert (two.path / "app" / "main.py").read_text(encoding="utf-8") == "x = 1\n"


def test_reusing_a_run_id_replaces_the_old_checkout(base: Path) -> None:
    create(base, "aaaaaaaaaaaa", "First attempt")
    again = create(base, "aaaaaaaaaaaa", "Second attempt")
    assert again.path.is_dir()


def test_run_ids_sharing_a_prefix_do_not_share_a_directory(base: Path) -> None:
    """Two concurrent benchmark runs of one task differ only in their tail;
    a truncated directory name would have them delete each other's work."""
    one = create(base, "bench-pagination-aaaaaa", "Add pagination")
    two = create(base, "bench-pagination-bbbbbb", "Add pagination")

    assert one.path != two.path
    assert one.path.is_dir() and two.path.is_dir()
    assert one.branch != two.branch, "two live runs must not commit to one branch"


# -- rollback ----------------------------------------------------------------


def test_removing_a_worktree_deletes_the_files_and_the_branch(base: Path) -> None:
    """Undo is a delete: nothing has to be untangled from anyone else's work."""
    worktree = create(base, "aaaaaaaaaaaa", "Doomed task")
    (worktree.path / "app" / "new.py").write_text("junk\n", encoding="utf-8")

    worktree.remove()

    assert not worktree.path.exists()
    assert worktree.branch not in git(base, "branch", "--list", worktree.branch)


def test_removing_one_run_leaves_the_other_untouched(base: Path) -> None:
    keep = create(base, "aaaaaaaaaaaa", "Keep this")
    doomed = create(base, "bbbbbbbbbbbb", "Discard this")

    doomed.remove()

    assert keep.path.is_dir()
    assert (keep.path / "app" / "main.py").exists()


def test_rollback_leaves_the_base_repository_clean(base: Path) -> None:
    worktree = create(base, "aaaaaaaaaaaa", "Doomed task")
    (worktree.path / "app" / "new.py").write_text("junk\n", encoding="utf-8")
    git(worktree.path, "add", "-A")
    git(worktree.path, "commit", "-m", "work to discard")

    worktree.remove()

    assert git(base, "status", "--porcelain") == ""
    assert not (base / "app" / "new.py").exists()


def test_removing_twice_does_not_raise(base: Path) -> None:
    """Rollback may be clicked twice, or race a cleanup."""
    worktree = create(base, "aaaaaaaaaaaa", "Doomed")
    worktree.remove()
    worktree.remove()


def test_removing_a_manually_deleted_checkout_still_tidies_up(base: Path) -> None:
    from app.workspace.provision import remove_tree

    worktree = create(base, "aaaaaaaaaaaa", "Doomed")
    remove_tree(worktree.path)

    worktree.remove()
    prune(base)

    assert str(worktree.path) not in list_worktrees(base)


# -- naming ------------------------------------------------------------------


def test_branch_names_are_readable_and_scoped(base: Path) -> None:
    name = branch_name("abcdef1234567890", "Add limit/offset pagination to GET /notes")
    assert name.startswith("agent/abcdef12-")
    assert " " not in name and "/" in name


def test_a_request_with_no_usable_characters_still_names_a_branch() -> None:
    assert branch_name("abcdef1234567890", "!!! ???").endswith("-task")
