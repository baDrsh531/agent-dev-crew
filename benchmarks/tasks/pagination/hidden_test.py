"""Hidden acceptance tests — pagination.

Copied into the workspace only after the run finishes. The crew never sees
these, so it cannot tune to them or weaken them.
"""

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


def seed(client: TestClient, count: int, tag: str = "all") -> None:
    for i in range(count):
        client.post("/notes", json={"title": f"n{i:03d}", "tags": [tag]})


def test_default_limit_is_20(client: TestClient) -> None:
    seed(client, 35)
    assert len(client.get("/notes").json()) == 20


def test_fewer_notes_than_the_limit_returns_all(client: TestClient) -> None:
    seed(client, 5)
    assert len(client.get("/notes").json()) == 5


def test_explicit_limit_is_honoured(client: TestClient) -> None:
    seed(client, 30)
    assert len(client.get("/notes", params={"limit": 7}).json()) == 7


def test_limit_above_100_is_capped_not_rejected(client: TestClient) -> None:
    seed(client, 130)
    response = client.get("/notes", params={"limit": 500})
    assert response.status_code == 200, "a limit over 100 must be capped, not rejected"
    assert len(response.json()) == 100


def test_offset_skips_notes(client: TestClient) -> None:
    seed(client, 30)
    titles = [n["title"] for n in client.get("/notes", params={"offset": 5, "limit": 3}).json()]
    assert titles == ["n005", "n006", "n007"]


def test_offset_beyond_the_end_returns_empty(client: TestClient) -> None:
    seed(client, 5)
    assert client.get("/notes", params={"offset": 50}).json() == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -1}, {"offset": -1}])
def test_invalid_parameters_return_422(client: TestClient, params: dict) -> None:
    assert client.get("/notes", params=params).status_code == 422


def test_tag_filter_is_applied_before_pagination(client: TestClient) -> None:
    for i in range(10):
        client.post("/notes", json={"title": f"work{i}", "tags": ["work"]})
    for i in range(10):
        client.post("/notes", json={"title": f"home{i}", "tags": ["home"]})

    page = client.get("/notes", params={"tag": "work", "limit": 4}).json()
    assert len(page) == 4
    assert all("work" in n["tags"] for n in page), "pagination must not leak other tags"


def test_results_stay_ordered_by_id(client: TestClient) -> None:
    seed(client, 25)
    ids = [n["id"] for n in client.get("/notes", params={"limit": 25}).json()]
    assert ids == sorted(ids)
