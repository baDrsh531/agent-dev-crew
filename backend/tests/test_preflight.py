"""Preflight: what must be refused before touching a repository you care about."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings
from app.workspace.preflight import PreflightFailed, assert_ready, check


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo, capture_output=True, text=True, check=False,
    )


def make_repo(tmp_path: Path, *, commit: bool = True, with_tests: bool = True) -> Path:
    repo = tmp_path / "their-project"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    if with_tests:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_app.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    git(repo, "init")
    if commit:
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "baseline")
    return repo


def external_settings(root: Path, tmp_path: Path, *, opted_in: bool = True) -> Settings:
    return Settings(
        llm_provider="fake",
        workspace_root=root,
        workspace_template=None,          # bring-your-own-project mode
        allow_external_workspace=opted_in,
        database_path=tmp_path / "t.db",
    )


def codes(settings: Settings) -> set[str]:
    return {i.code for i in check(settings) if i.blocking}


# -- managed workspaces are disposable, so almost nothing applies ------------


def test_managed_workspace_is_ready(tmp_path: Path, workspace: Path) -> None:
    settings = Settings(
        llm_provider="fake",
        workspace_root=workspace,
        workspace_template=workspace,     # managed
        database_path=tmp_path / "t.db",
    )
    assert codes(settings) == set()


# -- the self-modification guard --------------------------------------------


def test_the_crews_own_source_is_always_refused(tmp_path: Path) -> None:
    settings = Settings(
        llm_provider="fake",
        workspace_root=REPO_ROOT,
        workspace_template=REPO_ROOT / "demo-repo",   # even in managed mode
        allow_external_workspace=True,
        database_path=tmp_path / "t.db",
    )
    assert "self_modification" in codes(settings)


def test_a_parent_of_the_crews_source_is_refused(tmp_path: Path) -> None:
    settings = external_settings(REPO_ROOT.parent, tmp_path)
    assert "self_modification" in codes(settings)


# -- bring-your-own-project ---------------------------------------------------


def test_external_workspace_requires_an_explicit_opt_in(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    assert "not_opted_in" in codes(external_settings(repo, tmp_path, opted_in=False))


def test_a_clean_repository_with_tests_is_ready(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    assert codes(external_settings(repo, tmp_path)) == set()


def test_a_non_repository_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "just-a-folder"
    plain.mkdir()
    (plain / "a.py").write_text("x=1", encoding="utf-8")
    assert "not_a_repo" in codes(external_settings(plain, tmp_path))


def test_a_missing_directory_is_refused(tmp_path: Path) -> None:
    assert "missing" in codes(external_settings(tmp_path / "nowhere", tmp_path))


def test_uncommitted_work_is_refused(tmp_path: Path) -> None:
    """The run's diff must contain the run's work and nothing else."""
    repo = make_repo(tmp_path)
    (repo / "src" / "wip.py").write_text("half done\n", encoding="utf-8")
    assert "dirty_tree" in codes(external_settings(repo, tmp_path))


def test_a_detached_head_is_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                         capture_output=True, text=True, check=False).stdout.strip()
    git(repo, "checkout", sha)
    assert "detached_head" in codes(external_settings(repo, tmp_path))


def test_a_repository_without_tests_warns_but_does_not_block(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, with_tests=False)
    issues = check(external_settings(repo, tmp_path))
    no_tests = [i for i in issues if i.code == "no_tests"]
    assert no_tests and no_tests[0].blocking is False
    assert codes(external_settings(repo, tmp_path)) == set()


# -- assert_ready -------------------------------------------------------------


def test_assert_ready_raises_with_every_reason(tmp_path: Path) -> None:
    plain = tmp_path / "folder"
    plain.mkdir()
    with pytest.raises(PreflightFailed) as raised:
        assert_ready(external_settings(plain, tmp_path, opted_in=False))
    assert {i.code for i in raised.value.issues} >= {"not_opted_in", "not_a_repo"}


def test_assert_ready_passes_on_a_good_repository(tmp_path: Path) -> None:
    assert_ready(external_settings(make_repo(tmp_path), tmp_path))


def test_every_blocking_issue_offers_a_remedy(tmp_path: Path) -> None:
    """A refusal the user cannot act on is a dead end, not a guard rail."""
    plain = tmp_path / "folder"
    plain.mkdir()
    for issue in check(external_settings(plain, tmp_path, opted_in=False)):
        assert issue.remedy, f"{issue.code} tells the user nothing about how to proceed"
