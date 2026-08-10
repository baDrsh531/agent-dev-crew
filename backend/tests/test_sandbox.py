"""Confinement is the security boundary — it gets adversarial tests, not happy ones."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.workspace.sandbox import Sandbox, SandboxViolation


@pytest.mark.parametrize(
    "hostile",
    [
        "../secrets.txt",
        "app/../../escape.py",
        "app/../../../etc/passwd",
        "~/.ssh/id_rsa",
        "..\\..\\windows\\system32\\config",
        "./app/../../outside.txt",
    ],
)
def test_traversal_is_refused(sandbox: Sandbox, hostile: str) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.resolve(hostile)


@pytest.mark.parametrize("blocked", [".git/config", "app/../.git/HEAD", "node_modules/x/index.js", ".env"])
def test_protected_locations_are_refused(sandbox: Sandbox, blocked: str) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.resolve(blocked)


def test_absolute_path_outside_root_is_refused(sandbox: Sandbox, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(SandboxViolation):
        sandbox.resolve(str(outside))


def test_absolute_path_inside_root_is_accepted(sandbox: Sandbox) -> None:
    inside = sandbox.root / "app" / "main.py"
    assert sandbox.resolve(str(inside)) == inside.resolve()


def test_empty_path_is_refused(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.resolve("   ")


def test_read_and_write_round_trip(sandbox: Sandbox) -> None:
    sandbox.write_text("app/new.py", "print('x')\n")
    assert sandbox.read_text("app/new.py") == "print('x')\n"


def test_write_creates_parent_directories(sandbox: Sandbox) -> None:
    sandbox.write_text("deep/nested/dir/file.txt", "ok")
    assert (sandbox.root / "deep" / "nested" / "dir" / "file.txt").exists()


def test_read_missing_file_is_refused(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.read_text("app/nope.py")


def test_list_files_hides_protected_directories(sandbox: Sandbox) -> None:
    (sandbox.root / ".git").mkdir(exist_ok=True)
    (sandbox.root / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    assert all(".git" not in path for path in sandbox.list_files())


def test_relative_uses_forward_slashes(sandbox: Sandbox) -> None:
    assert sandbox.relative(sandbox.root / "app" / "main.py") == "app/main.py"
