"""Hidden acceptance tests — tag validation."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def clean():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_ten_tags_are_accepted(client: TestClient) -> None:
    tags = [f"t{i}" for i in range(10)]
    assert client.post("/notes", json={"title": "ok", "tags": tags}).status_code == 201


def test_eleven_tags_are_rejected(client: TestClient) -> None:
    tags = [f"t{i}" for i in range(11)]
    assert client.post("/notes", json={"title": "too many", "tags": tags}).status_code == 422


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_blank_tags_are_rejected(client: TestClient, bad: str) -> None:
    assert client.post("/notes", json={"title": "x", "tags": [bad]}).status_code == 422


def test_tag_of_exactly_30_characters_is_accepted(client: TestClient) -> None:
    assert client.post("/notes", json={"title": "x", "tags": ["a" * 30]}).status_code == 201


def test_tag_longer_than_30_characters_is_rejected(client: TestClient) -> None:
    assert client.post("/notes", json={"title": "x", "tags": ["a" * 31]}).status_code == 422


def test_duplicates_are_deduplicated_not_rejected(client: TestClient) -> None:
    response = client.post("/notes", json={"title": "x", "tags": ["work", "home", "work"]})
    assert response.status_code == 201, "duplicates must be accepted, not rejected"
    assert response.json()["tags"] == ["work", "home"], "order of first appearance is preserved"


def test_patch_enforces_the_same_rules(client: TestClient) -> None:
    note_id = client.post("/notes", json={"title": "x"}).json()["id"]
    assert client.patch(f"/notes/{note_id}", json={"tags": [""]}).status_code == 422
    assert client.patch(f"/notes/{note_id}", json={"tags": [f"t{i}" for i in range(11)]}).status_code == 422


def test_patch_deduplicates_too(client: TestClient) -> None:
    note_id = client.post("/notes", json={"title": "x"}).json()["id"]
    updated = client.patch(f"/notes/{note_id}", json={"tags": ["a", "a", "b"]})
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["a", "b"]


def test_notes_without_tags_still_work(client: TestClient) -> None:
    response = client.post("/notes", json={"title": "plain"})
    assert response.status_code == 201
    assert response.json()["tags"] == []


def test_existing_behaviour_is_unchanged(client: TestClient) -> None:
    note_id = client.post("/notes", json={"title": "keep", "body": "me"}).json()["id"]
    assert client.get(f"/notes/{note_id}").json()["body"] == "me"
    assert client.post("/notes", json={"body": "no title"}).status_code == 422
