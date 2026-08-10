"""Hidden acceptance tests — search."""

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


@pytest.fixture
def seeded(client: TestClient) -> TestClient:
    client.post("/notes", json={"title": "Grocery list", "body": "milk and eggs"})
    client.post("/notes", json={"title": "Meeting notes", "body": "discuss the MILK supplier"})
    client.post("/notes", json={"title": "Reading", "body": "chapter four"})
    return client


def titles(response) -> list[str]:
    return [n["title"] for n in response.json()]


def test_matches_the_title(seeded: TestClient) -> None:
    assert titles(seeded.get("/notes/search", params={"q": "grocery"})) == ["Grocery list"]


def test_matches_the_body(seeded: TestClient) -> None:
    assert "Reading" in titles(seeded.get("/notes/search", params={"q": "chapter"}))


def test_match_is_case_insensitive(seeded: TestClient) -> None:
    found = titles(seeded.get("/notes/search", params={"q": "milk"}))
    assert "Grocery list" in found and "Meeting notes" in found


def test_match_is_a_substring_not_a_whole_word(seeded: TestClient) -> None:
    assert "Grocery list" in titles(seeded.get("/notes/search", params={"q": "roce"}))


def test_no_match_returns_an_empty_list(seeded: TestClient) -> None:
    response = seeded.get("/notes/search", params={"q": "zzzznothing"})
    assert response.status_code == 200
    assert response.json() == []


def test_missing_q_returns_422(client: TestClient) -> None:
    assert client.get("/notes/search").status_code == 422


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_q_returns_422(client: TestClient, blank: str) -> None:
    assert client.get("/notes/search", params={"q": blank}).status_code == 422


def test_results_are_ordered_by_id(seeded: TestClient) -> None:
    ids = [n["id"] for n in seeded.get("/notes/search", params={"q": "e"}).json()]
    assert ids == sorted(ids)


def test_response_shape_matches_the_list_endpoint(seeded: TestClient) -> None:
    note = seeded.get("/notes/search", params={"q": "grocery"}).json()[0]
    assert {"id", "title", "body", "tags", "created_at", "updated_at"} <= set(note)


def test_existing_routes_still_work(seeded: TestClient) -> None:
    assert seeded.get("/health").status_code == 200
    assert len(seeded.get("/notes").json()) == 3
