"""Which server answers a call, under two different rules.

Interchangeable servers are balanced by run. Servers running *different*
models are chosen by the model the request asked for. The two compose, and the
composition is where this can go quietly wrong.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.roles import AgentRole
from app.llm.base import LLMRequest, LLMResponse, Usage
from app.llm.factory import build_client, lease_client, model_for
from app.llm.openai_client import EndpointUnavailable
from app.llm.pool import AllEndpointsDown, EndpointPool, ModelRouter


class StubServer:
    """Stands in for one llama.cpp server. Records what it was asked."""

    provider = "openai_compatible"

    def __init__(self, url: str, *, fails: bool = False, model: str = "qwen") -> None:
        self.base_url = url
        self.model = model
        self.fails = fails
        self.calls: list[str] = []
        self.models_error: Exception | None = None
        self.served = [model]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request.system)
        if self.fails:
            raise EndpointUnavailable(f"{self.base_url} is unreachable")
        return LLMResponse(
            content=[{"type": "text", "text": self.base_url}],
            stop_reason="end_turn", usage=Usage(output_tokens=1), model=self.model,
        )

    async def list_models(self) -> list[str]:
        if self.models_error:
            raise self.models_error
        return self.served

    async def aclose(self) -> None:
        return None


def pool_of(*servers: StubServer, cooldown: float = 30.0) -> EndpointPool:
    return EndpointPool(list(servers), cooldown_seconds=cooldown)


def ask(text: str = "hello") -> LLMRequest:
    return LLMRequest(model="qwen", system=text, messages=[])


# -- construction ------------------------------------------------------------


def test_a_pool_needs_at_least_one_server() -> None:
    with pytest.raises(ValueError, match="at least one"):
        EndpointPool([])


def test_a_single_configured_url_is_not_pooled() -> None:
    """A pool of one adds indirection and buys nothing."""
    settings = Settings(
        llm_provider="openai_compatible", openai_base_url="http://a:1/v1", openai_model="qwen"
    )
    assert not isinstance(build_client(settings), EndpointPool)


def test_several_urls_build_a_pool() -> None:
    settings = Settings(
        llm_provider="openai_compatible",
        openai_base_url="http://a:1/v1, http://b:2/v1 ,http://c:3/v1",
        openai_model="qwen",
    )
    client = build_client(settings)
    assert isinstance(client, EndpointPool)
    assert client.size == 3


def test_a_repeated_url_is_counted_once() -> None:
    """Two entries for one server would double its share of the load."""
    settings = Settings(
        llm_provider="openai_compatible",
        openai_base_url="http://a:1/v1,http://a:1/v1/,http://b:2/v1",
        openai_model="qwen",
    )
    assert settings.openai_base_urls == ["http://a:1/v1", "http://b:2/v1"]


def test_blank_entries_are_ignored() -> None:
    settings = Settings(
        llm_provider="openai_compatible",
        openai_base_url="http://a:1/v1, ,,http://b:2/v1,",
        openai_model="qwen",
    )
    assert len(settings.openai_base_urls) == 2


# -- spreading runs ----------------------------------------------------------


def test_runs_are_spread_across_the_servers() -> None:
    """Three servers and three runs must mean one run each."""
    pool = pool_of(StubServer("a"), StubServer("b"), StubServer("c"))
    leases = [pool.lease() for _ in range(3)]
    assert {lease.url for lease in leases} == {"a", "b", "c"}


def test_a_released_server_is_reused_first() -> None:
    pool = pool_of(StubServer("a"), StubServer("b"))
    first, second = pool.lease(), pool.lease()
    first.release()

    assert pool.lease().url == first.url
    assert second.url != first.url


def test_releasing_twice_does_not_free_the_slot_twice() -> None:
    """Otherwise a server would look idle while still carrying a run."""
    pool = pool_of(StubServer("a"), StubServer("b"))
    lease = pool.lease()
    lease.release()
    lease.release()

    assert [e.leases for e in pool.endpoints] == [0, 0]


async def test_a_lease_keeps_every_turn_on_the_same_server() -> None:
    """The point of pinning: the server already holds the conversation prefix."""
    a, b = StubServer("a"), StubServer("b")
    pool = pool_of(a, b)
    lease = pool.lease()

    for turn in range(4):
        await lease.complete(ask(f"turn {turn}"))

    assert len(a.calls) == 4 and b.calls == []


# -- failure -----------------------------------------------------------------


async def test_a_dead_server_hands_the_call_to_another() -> None:
    dead, alive = StubServer("dead", fails=True), StubServer("alive")
    pool = pool_of(dead, alive)

    assert (await pool.complete(ask())).text == "alive"


async def test_a_dead_server_leaves_the_rotation() -> None:
    dead, alive = StubServer("dead", fails=True), StubServer("alive")
    pool = pool_of(dead, alive)
    await pool.complete(ask())

    assert pool.status()[0]["healthy"] is False
    assert pool.status()[0]["cooldown_remaining"] > 0


async def test_a_run_follows_its_work_to_the_server_that_answered() -> None:
    """Staying pinned to a dead server would burn one doomed attempt per turn."""
    dead, alive = StubServer("dead", fails=True), StubServer("alive")
    pool = pool_of(dead, alive)
    lease = pool.lease()
    assert lease.url == "dead"

    await lease.complete(ask("first"))
    await lease.complete(ask("second"))

    assert lease.url == "alive"
    assert len(dead.calls) == 1, "the dead server must be tried once, not once per turn"
    assert len(alive.calls) == 2


async def test_a_failover_moves_the_lease_rather_than_double_counting() -> None:
    dead, alive = StubServer("dead", fails=True), StubServer("alive")
    pool = pool_of(dead, alive)
    lease = pool.lease()
    await lease.complete(ask())

    assert [e.leases for e in pool.endpoints] == [0, 1]


async def test_when_every_server_is_down_the_error_names_them_all() -> None:
    pool = pool_of(StubServer("a", fails=True), StubServer("b", fails=True))

    with pytest.raises(AllEndpointsDown) as caught:
        await pool.complete(ask())

    assert "a" in str(caught.value) and "b" in str(caught.value)


async def test_a_bad_request_is_not_retried_elsewhere() -> None:
    """A 4xx is the request's fault: retrying hides a bug behind a failover."""

    class Rejecting(StubServer):
        async def complete(self, request: LLMRequest) -> LLMResponse:
            self.calls.append(request.system)
            raise RuntimeError("400: schema is malformed")

    first, second = Rejecting("a"), StubServer("b")
    pool = pool_of(first, second)

    with pytest.raises(RuntimeError, match="400"):
        await pool.complete(ask())
    assert second.calls == [], "the second server must not see a request known to be wrong"


async def test_a_recovered_server_comes_back_after_its_cooldown() -> None:
    dead, alive = StubServer("dead", fails=True), StubServer("alive")
    pool = pool_of(dead, alive, cooldown=0.0)
    await pool.complete(ask())

    dead.fails = False
    assert pool.status()[0]["healthy"] is True


async def test_all_servers_in_cooldown_still_get_tried() -> None:
    """Refusing outright would turn a transient outage into a dead system."""
    a, b = StubServer("a", fails=True), StubServer("b", fails=True)
    pool = pool_of(a, b)
    with pytest.raises(AllEndpointsDown):
        await pool.complete(ask())

    a.fails = b.fails = False
    assert (await pool.complete(ask())).text in {"a", "b"}


# -- verification ------------------------------------------------------------


async def test_matching_servers_are_reported_as_agreeing() -> None:
    result = await pool_of(StubServer("a"), StubServer("b")).verify()
    assert result["agree"] is True


async def test_servers_running_different_models_are_reported() -> None:
    """A pool that disagrees invalidates every comparison made across it."""
    a, b = StubServer("a"), StubServer("b")
    b.served = ["a-completely-different-model"]

    result = await pool_of(a, b).verify()

    assert result["agree"] is False
    assert result["served"]["b"] == ["a-completely-different-model"]


async def test_a_server_that_cannot_be_asked_is_not_taken_as_agreement() -> None:
    a, b = StubServer("a"), StubServer("b")
    b.models_error = EndpointUnavailable("b is unreachable")
    pool = pool_of(a, b)

    result = await pool.verify()

    assert result["served"]["b"] == []
    assert "unreachable" in pool.status()[1]["last_error"]


# -- different models on different servers -----------------------------------


def routed(**extra) -> Settings:
    return Settings(
        llm_provider="openai_compatible",
        openai_base_url="http://big:1/v1",
        openai_model="big-model",
        openai_role_endpoints="documenter=http://small:2/v1|small-model",
        **extra,
    )


def test_a_routed_role_reports_its_own_model() -> None:
    """The name is not decoration: it is what the router dispatches on."""
    settings = routed()
    assert model_for(AgentRole.DOCUMENTER, settings) == "small-model"
    assert model_for(AgentRole.DEVELOPER, settings) == "big-model"


def test_an_entry_without_a_model_is_refused() -> None:
    """Discovering a 404 mid-run is worse than refusing at startup."""
    with pytest.raises(ValueError, match="model name is required"):
        Settings(openai_role_endpoints="documenter=http://small:2/v1").openai_role_routes


def test_role_routes_are_parsed_into_url_and_model() -> None:
    routes = routed().openai_role_routes
    assert routes == {"documenter": ("http://small:2/v1", "small-model")}


async def test_the_router_sends_each_model_to_its_own_server() -> None:
    big, small = StubServer("big", model="big-model"), StubServer("small", model="small-model")
    router = ModelRouter(big, {"small-model": small})

    await router.complete(LLMRequest(model="small-model", system="doc", messages=[]))
    await router.complete(LLMRequest(model="big-model", system="code", messages=[]))

    assert small.calls == ["doc"]
    assert big.calls == ["code"]


async def test_an_unrouted_model_falls_back_to_the_main_server() -> None:
    big, small = StubServer("big"), StubServer("small")
    router = ModelRouter(big, {"small-model": small})

    await router.complete(LLMRequest(model="anything-else", system="s", messages=[]))

    assert big.calls == ["s"] and small.calls == []


def test_a_leased_run_still_honours_the_role_routes() -> None:
    """Leasing and then ignoring the routes would silently send the documenter
    to the big model — the bug this composition exists to prevent."""
    client, release = lease_client(routed())
    assert isinstance(client, ModelRouter)
    assert client.routes() == {"small-model": "http://small:2/v1"}
    release()


def test_without_role_routes_nothing_is_wrapped() -> None:
    settings = Settings(
        llm_provider="openai_compatible",
        openai_base_url="http://big:1/v1", openai_model="big-model",
    )
    client, release = lease_client(settings)
    assert client is None, "one server and no routes needs no composition at all"
    release()
