"""Provisioning must never clobber work in progress."""

from __future__ import annotations

from pathlib import Path

from app.workspace.provision import is_empty, provision


def make_template(tmp_path: Path) -> Path:
    template = tmp_path / "template"
    (template / "app").mkdir(parents=True)
    (template / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (template / "README.md").write_text("# demo\n", encoding="utf-8")
    (template / ".git").mkdir()
    (template / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (template / "__pycache__").mkdir()
    (template / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    return template


def test_provision_copies_the_template(tmp_path: Path) -> None:
    template = make_template(tmp_path)
    root = tmp_path / "workspace"

    assert provision(root, template) is True
    assert (root / "app" / "main.py").read_text(encoding="utf-8") == "x = 1\n"


def test_provision_excludes_git_and_caches(tmp_path: Path) -> None:
    template = make_template(tmp_path)
    root = tmp_path / "workspace"

    provision(root, template)

    # A copied .git would make the run continue someone else's history.
    assert not (root / ".git").exists()
    assert not (root / "__pycache__").exists()


def test_existing_workspace_is_left_alone(tmp_path: Path) -> None:
    template = make_template(tmp_path)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "work-in-progress.py").write_text("precious", encoding="utf-8")

    assert provision(root, template) is False
    assert (root / "work-in-progress.py").exists()
    assert not (root / "app").exists()


def test_force_recreates_the_workspace(tmp_path: Path) -> None:
    template = make_template(tmp_path)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "stale.py").write_text("old run", encoding="utf-8")

    assert provision(root, template, force=True) is True
    assert not (root / "stale.py").exists()
    assert (root / "app" / "main.py").exists()


def test_no_template_just_creates_the_directory(tmp_path: Path) -> None:
    root = tmp_path / "workspace"

    assert provision(root, None) is False
    assert root.is_dir()


def test_missing_template_does_not_raise(tmp_path: Path) -> None:
    root = tmp_path / "workspace"

    assert provision(root, tmp_path / "nowhere") is False
    assert root.is_dir()


def test_force_removes_read_only_files(tmp_path: Path) -> None:
    """Git marks `.git/objects` read-only; on Windows that blocks rmtree."""
    import os
    import stat

    template = make_template(tmp_path)
    root = tmp_path / "workspace"
    root.mkdir()
    locked = root / "locked.bin"
    locked.write_text("git object", encoding="utf-8")
    os.chmod(locked, stat.S_IREAD)

    assert provision(root, template, force=True) is True
    assert not locked.exists()
    assert (root / "app" / "main.py").exists()


def test_force_reuses_the_directory_rather_than_recreating_it(tmp_path: Path) -> None:
    """Windows refuses to remove a directory that is a live process's cwd."""
    template = make_template(tmp_path)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "stale.txt").write_text("old", encoding="utf-8")
    inode_before = root.stat().st_ino

    provision(root, template, force=True)

    assert root.stat().st_ino == inode_before, "the workspace directory itself must survive"
    assert not (root / "stale.txt").exists()
    assert (root / "app" / "main.py").exists()


def test_is_empty(tmp_path: Path) -> None:
    assert is_empty(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    assert is_empty(tmp_path / "empty")
    (tmp_path / "empty" / "f").write_text("x", encoding="utf-8")
    assert not is_empty(tmp_path / "empty")
