"""Reference solution — the pre-existing suite, migrated to authenticate.

Same assertions as before; writes now carry a token. This is the migration the
task asks for, and it is why the reference solution has to ship it: adding auth
necessarily breaks a suite that writes anonymously.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import create_access_token
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


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token('tester')}"}


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_read_note(client: TestClient, auth) -> None:
    created = client.post("/notes", json={"title": "Shopping", "body": "milk"}, headers=auth)
    assert created.status_code == 201
    note_id = created.json()["id"]

    fetched = client.get(f"/notes/{note_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Shopping"


def test_list_filters_by_tag(client: TestClient, auth) -> None:
    client.post("/notes", json={"title": "A", "tags": ["work"]}, headers=auth)
    client.post("/notes", json={"title": "B", "tags": ["home"]}, headers=auth)

    titles = [n["title"] for n in client.get("/notes", params={"tag": "work"}).json()]
    assert titles == ["A"]


def test_update_changes_only_supplied_fields(client: TestClient, auth) -> None:
    note_id = client.post(
        "/notes", json={"title": "Draft", "body": "keep me"}, headers=auth
    ).json()["id"]

    updated = client.patch(f"/notes/{note_id}", json={"title": "Final"}, headers=auth).json()
    assert updated["title"] == "Final"
    assert updated["body"] == "keep me"


def test_missing_note_returns_404(client: TestClient, auth) -> None:
    assert client.get("/notes/999").status_code == 404
    assert client.patch("/notes/999", json={"title": "x"}, headers=auth).status_code == 404
    assert client.delete("/notes/999", headers=auth).status_code == 404


def test_delete_removes_note(client: TestClient, auth) -> None:
    note_id = client.post("/notes", json={"title": "Temp"}, headers=auth).json()["id"]
    assert client.delete(f"/notes/{note_id}", headers=auth).status_code == 204
    assert client.get(f"/notes/{note_id}").status_code == 404


def test_title_is_required(client: TestClient, auth) -> None:
    assert client.post("/notes", json={"body": "no title"}, headers=auth).status_code == 422
