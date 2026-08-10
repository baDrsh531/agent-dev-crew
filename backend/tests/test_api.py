"""HTTP surface, exercised against the fake provider end to end."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.config as config_module
import app.orchestrator.service as service_module
import app.store.broker as broker_module
import app.store.database as database_module
from app.store.database import get_database


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    workspace = tmp_path / "ws"
    (workspace / "app").mkdir(parents=True)
    (workspace / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("APPROVAL_MODE", "auto")
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))

    config_module.reset_settings()
    database_module.reset_database()
    service_module.reset_service()
    broker_module._broker = None

    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as test_client:
        yield test_client

    config_module.reset_settings()
    database_module.reset_database()
    service_module.reset_service()


def wait_until_finished(client: TestClient, run_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    terminal = {"succeeded", "failed", "escalated", "cancelled"}
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/runs/{run_id}").json()
        if snapshot["run"]["status"] in terminal:
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s")


def test_health_reports_the_active_provider(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["provider"] == "fake"


def test_config_exposes_roles_limits_and_permissions(client: TestClient) -> None:
    body = client.get("/api/config").json()

    assert {r["id"] for r in body["roles"]} >= {"analyst", "architect", "developer", "qa", "documenter"}
    assert body["limits"]["max_qa_iterations"] >= 1
    # The security story is machine-readable, not just prose in a README.
    assert body["permissions"]["analyst"]["write_file"] == "denied"
    assert body["permissions"]["developer"]["write_file"] == "approval"
    assert body["permissions"]["qa"]["edit_file"] == "denied"


def test_create_run_returns_an_id_and_the_run_completes(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]

    snapshot = wait_until_finished(client, run_id)

    assert snapshot["run"]["status"] in {"succeeded", "failed", "escalated"}
    assert snapshot["events"], "a finished run must have an event log"
    assert snapshot["run"]["branch"].startswith("agent/")


def test_run_produces_the_full_artifact_chain(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    snapshot = wait_until_finished(client, run_id)

    if snapshot["run"]["status"] == "succeeded":
        kinds = {a["kind"] for a in snapshot["artifacts"]}
        assert kinds == {
            "intake", "spec", "plan", "changeset", "evidence", "qa_report", "docs_bundle"
        }


def test_events_can_be_replayed_incrementally(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    wait_until_finished(client, run_id)

    everything = client.get(f"/api/runs/{run_id}/events").json()["events"]
    tail = client.get(f"/api/runs/{run_id}/events", params={"after_seq": 3}).json()["events"]

    assert [e["seq"] for e in everything] == list(range(1, len(everything) + 1))
    assert all(e["seq"] > 3 for e in tail)


def test_short_requests_are_rejected(client: TestClient) -> None:
    assert client.post("/api/runs", json={"request": "hi"}).status_code == 422


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.get("/api/runs/does-not-exist/events").status_code == 404


def test_unknown_approval_is_404(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    response = client.post(
        f"/api/runs/{run_id}/approvals/nope", json={"approved": True, "reason": ""}
    )
    assert response.status_code == 404


def test_preflight_reports_a_managed_workspace_as_ready(client: TestClient) -> None:
    body = client.get("/api/workspace/preflight").json()
    assert body["ready"] is True
    assert body["managed"] is True
    assert body["issues"] == []


def test_resumable_reports_nothing_left_after_a_finished_run(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    snapshot = wait_until_finished(client, run_id)

    body = client.get(f"/api/runs/{run_id}/resumable").json()
    if snapshot["run"]["status"] == "succeeded":
        assert body["next_phase"] == "done"
        assert body["resumable"] is False
        assert set(body["completed"]) == {"spec", "plan", "changeset", "qa_report", "docs_bundle"}


def test_resuming_a_finished_run_is_a_conflict(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    wait_until_finished(client, run_id)

    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409


def test_replay_creates_a_second_run_from_the_recording(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    snapshot = wait_until_finished(client, run_id)
    if snapshot["run"]["status"] != "succeeded":
        pytest.skip("source run did not succeed; nothing to replay")

    body = client.post(f"/api/runs/{run_id}/replay").json()
    assert body["replay_of"] == run_id
    replayed = wait_until_finished(client, body["run_id"])
    assert replayed["run"]["status"] == "succeeded"
    assert replayed["run"]["cost_usd"] == 0.0, "a replay calls no model"


def test_replaying_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.post("/api/runs/nope/replay").status_code == 404


def test_resumable_for_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope/resumable").status_code == 404


# -- per-run checkouts and rollback ------------------------------------------


def test_a_run_works_in_its_own_checkout_not_the_shared_root(client: TestClient) -> None:
    """Isolation is the whole point: two runs must not edit the same files."""
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    wait_until_finished(client, run_id)

    record = client.get(f"/api/runs/{run_id}").json()["run"]
    checkout = Path(record["worktree_path"])
    assert checkout.is_dir()
    assert checkout.resolve() != Path(config_module.get_settings().workspace_root).resolve()


def test_two_runs_get_separate_checkouts(client: TestClient) -> None:
    first = client.post("/api/runs", json={"request": "First task here"}).json()["run_id"]
    wait_until_finished(client, first)
    second = client.post("/api/runs", json={"request": "Second task here"}).json()["run_id"]
    wait_until_finished(client, second)

    paths = {
        client.get(f"/api/runs/{r}").json()["run"]["worktree_path"] for r in (first, second)
    }
    assert len(paths) == 2, "each run must have its own working tree"


def test_rollback_removes_the_checkout_and_the_branch(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    wait_until_finished(client, run_id)
    checkout = Path(client.get(f"/api/runs/{run_id}").json()["run"]["worktree_path"])

    body = client.post(f"/api/runs/{run_id}/rollback").json()

    assert body["ok"] is True
    assert not checkout.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", body["branch"]],
        cwd=config_module.get_settings().workspace_root,
        capture_output=True, text=True, check=False,
    ).stdout
    assert body["branch"] not in branches


def test_rollback_leaves_other_runs_alone(client: TestClient) -> None:
    keep = client.post("/api/runs", json={"request": "Keep this work"}).json()["run_id"]
    wait_until_finished(client, keep)
    doomed = client.post("/api/runs", json={"request": "Discard this work"}).json()["run_id"]
    wait_until_finished(client, doomed)

    client.post(f"/api/runs/{doomed}/rollback")

    kept = Path(client.get(f"/api/runs/{keep}").json()["run"]["worktree_path"])
    assert kept.is_dir()


def test_rolling_back_twice_is_a_conflict(client: TestClient) -> None:
    """The second click has nothing left to discard, and must say so."""
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    wait_until_finished(client, run_id)

    assert client.post(f"/api/runs/{run_id}/rollback").status_code == 200
    assert client.post(f"/api/runs/{run_id}/rollback").status_code == 409


def test_rolling_back_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.post("/api/runs/nope/rollback").status_code == 404


def test_resetting_the_workspace_removes_the_checkouts_first(client: TestClient) -> None:
    """Otherwise the reset deletes the base .git and strands every checkout."""
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    wait_until_finished(client, run_id)
    checkout = Path(client.get(f"/api/runs/{run_id}").json()["run"]["worktree_path"])
    assert checkout.is_dir()

    body = client.post("/api/workspace/reset").json()

    assert body["checkouts_discarded"] >= 1
    assert not checkout.exists()
    assert client.get(f"/api/runs/{run_id}").json()["run"]["worktree_path"] == ""


def test_runs_are_listed_newest_first(client: TestClient) -> None:
    first = client.post("/api/runs", json={"request": "First task here"}).json()["run_id"]
    wait_until_finished(client, first)
    second = client.post("/api/runs", json={"request": "Second task here"}).json()["run_id"]
    wait_until_finished(client, second)

    ids = [r["id"] for r in client.get("/api/runs").json()["runs"]]
    assert ids.index(second) < ids.index(first)


# -- the diff ----------------------------------------------------------------


def finished_run(client: TestClient) -> str:
    run_id = client.post("/api/runs", json={"request": "Add JWT authentication"}).json()["run_id"]
    wait_until_finished(client, run_id)
    return run_id


def test_the_diff_is_recomputed_not_remembered(client: TestClient) -> None:
    """It used to come from the live engine, so every past run's diff vanished
    when the process restarted — exactly the runs someone is reviewing."""
    run_id = finished_run(client)
    service_module.reset_service()          # as if the server had restarted

    body = client.get(f"/api/runs/{run_id}/diff").json()

    assert body["available"] is True
    assert body["branch"].startswith("agent/")


def test_a_file_the_run_created_appears_in_the_diff(client: TestClient) -> None:
    """`git diff` ignores untracked files, so a run whose whole contribution
    was creating files showed nothing at all."""
    run_id = finished_run(client)
    checkout = Path(client.get(f"/api/runs/{run_id}").json()["run"]["worktree_path"])
    (checkout / "brand_new.py").write_text("VALUE = 1\n", encoding="utf-8")

    diff = client.get(f"/api/runs/{run_id}/diff").json()["diff"]

    assert "brand_new.py" in diff
    assert "+VALUE = 1" in diff


def test_an_ignored_file_stays_out_of_the_diff(client: TestClient) -> None:
    """Otherwise __pycache__ and .venv would drown every real change."""
    run_id = finished_run(client)
    checkout = Path(client.get(f"/api/runs/{run_id}").json()["run"]["worktree_path"])
    (checkout / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    (checkout / "secret.txt").write_text("do not show me\n", encoding="utf-8")

    diff = client.get(f"/api/runs/{run_id}/diff").json()["diff"]

    assert "do not show me" not in diff


def test_a_run_that_never_branched_says_so_rather_than_404(client: TestClient) -> None:
    """'no diff yet' and 'no such run' are different answers."""
    get_database().create_run("never-started", "a task that never ran")

    response = client.get("/api/runs/never-started/diff")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["reason"]


def test_the_diff_of_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope/diff").status_code == 404


# -- the workspace tree ------------------------------------------------------


def test_the_tree_shows_what_the_run_touched(client: TestClient) -> None:
    run_id = finished_run(client)
    checkout = Path(client.get(f"/api/runs/{run_id}").json()["run"]["worktree_path"])
    (checkout / "added_by_the_run.py").write_text("X = 1\n", encoding="utf-8")

    body = client.get(f"/api/runs/{run_id}/workspace").json()

    assert body["available"] is True
    touched = {f["path"] for f in body["files"] if f["touched"]}
    assert "added_by_the_run.py" in touched


def test_the_tree_never_shows_what_the_agents_cannot_see(client: TestClient) -> None:
    """Path containment is an architectural claim; a tree that showed more than
    a tool call can reach would misrepresent the very thing it makes visible."""
    run_id = finished_run(client)
    checkout = Path(client.get(f"/api/runs/{run_id}").json()["run"]["worktree_path"])
    (checkout / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (checkout / "__pycache__").mkdir(exist_ok=True)
    (checkout / "__pycache__" / "x.pyc").write_bytes(b"\x00")

    body = client.get(f"/api/runs/{run_id}/workspace").json()

    paths = {f["path"] for f in body["files"]}
    assert not any(".env" in p or "__pycache__" in p for p in paths)
    assert ".env" in body["blocked"], "what is withheld is named, not silently omitted"


def test_the_tree_of_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope/workspace").status_code == 404


# -- per-run token ceiling ---------------------------------------------------


def test_a_run_can_be_given_its_own_token_ceiling(client: TestClient) -> None:
    """So a run that escalated on the budget can be relaunched with more room
    without editing .env and restarting the server."""
    run_id = client.post(
        "/api/runs",
        json={"request": "Add JWT authentication", "max_tokens": 55_000},
    ).json()["run_id"]
    snapshot = wait_until_finished(client, run_id)

    assert snapshot["budget"]["max_tokens"] == 55_000


def test_the_ceiling_does_not_leak_into_the_next_run(client: TestClient) -> None:
    """It is a per-run override, not a setting change."""
    first = client.post(
        "/api/runs", json={"request": "Add JWT authentication", "max_tokens": 55_000},
    ).json()["run_id"]
    wait_until_finished(client, first)

    second = client.post("/api/runs", json={"request": "Add pagination here"}).json()["run_id"]
    snapshot = wait_until_finished(client, second)

    default = client.get("/api/config").json()["limits"]["max_tokens_per_run"]
    assert snapshot["budget"]["max_tokens"] == default


def test_an_absurdly_small_ceiling_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/runs", json={"request": "Add JWT authentication", "max_tokens": 100},
    )
    assert response.status_code == 422


# -- the budget survives the process that produced it ------------------------


def test_a_finished_run_still_reports_its_budget_after_a_restart(client: TestClient) -> None:
    """It used to come from the live engine, so a completed 400k-token run read
    as having used zero once the process that ran it was gone — and the ceiling
    went with it, leaving the gauges nothing to measure against."""
    run_id = finished_run(client)
    live = client.get(f"/api/runs/{run_id}").json()["budget"]
    assert live and live["tool_calls_used"] is not None

    service_module.reset_service()          # as if the server had restarted

    after = client.get(f"/api/runs/{run_id}").json()["budget"]
    assert after is not None, "the event log holds it; it must be read back"
    assert after["tokens_used"] == live["tokens_used"]
    assert after["max_tokens"] == live["max_tokens"]
    assert after["tool_calls_used"] == live["tool_calls_used"]


def test_a_run_with_no_budget_event_reports_none_rather_than_zero(client: TestClient) -> None:
    """Zero and 'never measured' are different, and a gauge cannot show both."""
    get_database().create_run("no-events", "a run that never started")
    assert client.get("/api/runs/no-events").json()["budget"] is None
