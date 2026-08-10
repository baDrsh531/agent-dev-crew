"""Machine-gathered evidence: what QA is handed as fact.

The secret scanner gets the most attention because a scanner that cries wolf
is one a reviewer learns to wave through — which is strictly worse than having
none, since it also buys false confidence.
"""

from __future__ import annotations

import pytest

from app.quality.evidence import Check, Evidence, measure_diff, scan_for_secrets


def diff_adding(*lines: str) -> str:
    body = "\n".join(f"+{line}" for line in lines)
    return f"diff --git a/app/x.py b/app/x.py\n--- a/app/x.py\n+++ b/app/x.py\n@@ -1 +1 @@\n{body}\n"


# -- secret scanning ---------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"',
        'token = "ghp_16CharactersOrMoreHere00"',
        'SLACK = "xoxb-1234567890-abcdefghij"',
        'password = "hunter2hunter2"',
        'api_key = "sk-live-9f8a7b6c5d4e3f2a"',
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_credentials_in_added_lines_are_caught(line: str) -> None:
    check = scan_for_secrets(diff_adding(line))
    assert check.passed is False
    assert not check.skipped


@pytest.mark.parametrize(
    "line",
    [
        'SECRET = os.environ["JWT_SECRET"]',
        'password = os.getenv("DB_PASSWORD")',
        'api_key = settings.openai_api_key',
        'token = "changeme"',
        'password = "placeholder"',
        'key = "{{ vault_secret }}"',
        "def rotate_token(token: str) -> None:",
        "# never hardcode a password here",
    ],
)
def test_obvious_non_credentials_do_not_fire(line: str) -> None:
    """False positives are what make a scanner ignorable."""
    assert scan_for_secrets(diff_adding(line)).passed is True


def test_only_added_lines_are_scanned() -> None:
    """Reporting pre-existing findings on every run turns the scan into noise."""
    diff = (
        "diff --git a/app/x.py b/app/x.py\n"
        "--- a/app/x.py\n+++ b/app/x.py\n"
        '-AWS = "AKIAIOSFODNN7EXAMPLE"\n'
        ' CONTEXT = "AKIAIOSFODNN7EXAMPLE"\n'
        "+clean = 1\n"
    )
    assert scan_for_secrets(diff).passed is True


def test_the_scan_reports_what_it_found() -> None:
    check = scan_for_secrets(diff_adding('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'))
    assert "AWS access key" in check.detail


def test_an_empty_diff_is_not_a_failure() -> None:
    assert scan_for_secrets("").passed is True


# -- diff measurement --------------------------------------------------------


def test_change_size_counts_files_and_lines() -> None:
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n+one\n+two\n-gone\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n+three\n"
    )
    check = measure_diff(diff)
    assert "2 file(s)" in check.detail
    assert "+3/-1" in check.detail
    assert check.passed, "size is information, not a defect"


def test_file_headers_are_not_counted_as_changed_lines() -> None:
    """`+++ b/file` starts with '+' and would inflate every count."""
    check = measure_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n+real\n")
    assert "+1/-0" in check.detail


# -- the evidence block ------------------------------------------------------


def test_a_skipped_check_is_stated_not_hidden() -> None:
    """Silence about a check that never ran reads as a clean result."""
    evidence = Evidence(checks=[Check("lint (ruff)", True, "not installed", skipped=True)])
    rendered = evidence.render()
    assert "SKIPPED" in rendered
    assert "not installed" in rendered


def test_failures_are_listed_for_the_report() -> None:
    evidence = Evidence(checks=[
        Check("test suite", False, "2 failed"),
        Check("secret scan", True, "clean"),
        Check("lint (ruff)", True, "not installed", skipped=True),
    ])
    assert [c.name for c in evidence.failures] == ["test suite"]
    assert evidence.as_dict()["failed"] == ["test suite"]


def test_a_skipped_check_is_not_a_failure() -> None:
    evidence = Evidence(checks=[Check("lint", True, "absent", skipped=True)])
    assert evidence.failures == []


def test_empty_evidence_says_so_rather_than_rendering_nothing() -> None:
    assert Evidence().render() == "no checks were run"
