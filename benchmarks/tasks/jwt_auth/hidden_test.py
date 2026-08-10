"""Hidden acceptance tests — JWT authentication.

The hardest task in the suite: a new dependency, a new module with a contracted
interface, per-route authorisation rules, and the existing suite to migrate.

`app.auth` is imported through a fixture rather than at module scope on
purpose. A missing module must make the tests that need it **fail**, not skip
the whole file — a crew that did nothing at all should score zero, not "not
applicable". The public-route tests still run either way, so a partial
implementation scores partially.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture
def auth():
    try:
        return importlib.import_module("app.auth")
    except Exception as exc:  # noqa: BLE001 - any import failure is a task failure
        pytest.fail(f"app/auth.py is required by the task but could not be imported: {exc}")


@pytest.fixture(autouse=True)
def clean():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(auth) -> dict[str, str]:
    return bearer(auth.create_access_token("alice"))


@pytest.fixture
def admin_headers(auth) -> dict[str, str]:
    return bearer(auth.create_access_token("root", role="admin"))


# -- the contracted interface ------------------------------------------------


def test_create_access_token_exists_with_the_agreed_signature(auth) -> None:
    token = auth.create_access_token("alice")
    assert isinstance(token, str) and token.count(".") == 2, "expected a JWT"


def test_token_carries_sub_and_role_claims(auth) -> None:
    import jwt  # the task allows installing pyjwt

    claims = jwt.decode(
        auth.create_access_token("alice", role="admin"),
        "dev-secret", algorithms=["HS256"],
    )
    assert claims["sub"] == "alice"
    assert claims["role"] == "admin"


# -- public routes -----------------------------------------------------------


def test_health_stays_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_listing_notes_stays_public(client: TestClient) -> None:
    assert client.get("/notes").status_code == 200


def test_reading_one_note_stays_public(client: TestClient, user_headers) -> None:
    note_id = client.post("/notes", json={"title": "public"}, headers=user_headers).json()["id"]
    assert client.get(f"/notes/{note_id}").status_code == 200


# -- protected routes --------------------------------------------------------


def test_writing_without_a_token_is_401(client: TestClient) -> None:
    assert client.post("/notes", json={"title": "nope"}).status_code == 401


def test_writing_with_a_valid_token_succeeds(client: TestClient, user_headers) -> None:
    assert client.post("/notes", json={"title": "yes"}, headers=user_headers).status_code == 201


def test_patch_and_delete_require_a_token(client: TestClient, user_headers) -> None:
    note_id = client.post("/notes", json={"title": "x"}, headers=user_headers).json()["id"]
    assert client.patch(f"/notes/{note_id}", json={"title": "y"}).status_code == 401
    assert client.delete(f"/notes/{note_id}").status_code == 401


def test_a_garbage_token_is_401(client: TestClient) -> None:
    assert client.post("/notes", json={"title": "x"}, headers=bearer("not.a.token")).status_code == 401


def test_an_expired_token_is_401(client: TestClient, auth) -> None:
    expired = auth.create_access_token("alice", expires_in=-60)
    assert client.post("/notes", json={"title": "x"}, headers=bearer(expired)).status_code == 401


# -- admin -------------------------------------------------------------------


def test_admin_purge_rejects_an_anonymous_caller(client: TestClient) -> None:
    assert client.delete("/admin/notes").status_code == 401


def test_admin_purge_forbids_a_non_admin_token(client: TestClient, user_headers) -> None:
    response = client.delete("/admin/notes", headers=user_headers)
    assert response.status_code == 403, "a valid non-admin token must be 403, not 401"


def test_admin_purge_allows_an_admin_token(client: TestClient, admin_headers, user_headers) -> None:
    client.post("/notes", json={"title": "doomed"}, headers=user_headers)
    assert client.delete("/admin/notes", headers=admin_headers).status_code == 204
    assert client.get("/notes").json() == []
