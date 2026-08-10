"""Behaviour the notes API already guarantees.

These pass today. The agent crew must keep them passing while it adds new
behaviour — a change that turns any of these red is a regression, and QA is
expected to catch it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_read_note(client: TestClient) -> None:
    created = client.post("/notes", json={"title": "Shopping", "body": "milk"})
    assert created.status_code == 201
    note_id = created.json()["id"]

    fetched = client.get(f"/notes/{note_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Shopping"


def test_list_filters_by_tag(client: TestClient) -> None:
    client.post("/notes", json={"title": "A", "tags": ["work"]})
    client.post("/notes", json={"title": "B", "tags": ["home"]})

    titles = [n["title"] for n in client.get("/notes", params={"tag": "work"}).json()]
    assert titles == ["A"]


def test_update_changes_only_supplied_fields(client: TestClient) -> None:
    note_id = client.post("/notes", json={"title": "Draft", "body": "keep me"}).json()["id"]

    updated = client.patch(f"/notes/{note_id}", json={"title": "Final"}).json()
    assert updated["title"] == "Final"
    assert updated["body"] == "keep me"


def test_missing_note_returns_404(client: TestClient) -> None:
    assert client.get("/notes/999").status_code == 404
    assert client.patch("/notes/999", json={"title": "x"}).status_code == 404
    assert client.delete("/notes/999").status_code == 404


def test_delete_removes_note(client: TestClient) -> None:
    note_id = client.post("/notes", json={"title": "Temp"}).json()["id"]
    assert client.delete(f"/notes/{note_id}").status_code == 204
    assert client.get(f"/notes/{note_id}").status_code == 404


def test_title_is_required(client: TestClient) -> None:
    assert client.post("/notes", json={"body": "no title"}).status_code == 422
