"""Several interchangeable model servers behind one client.

Now that a run has its own git worktree, runs can overlap — and a single
llama.cpp server answers one request at a time. Three servers should therefore
mean three runs at once, and a benchmark suite that takes a third as long.

The routing decision that matters is **what to pin, and for how long**. A local
server keeps a prompt cache, and an agent loop sends ever-longer prefixes of the
same conversation: turn 5 shares everything but its tail with turn 4. Route
turn 5 to a different server and that server must prefill the whole conversation
from scratch. So the unit of routing here is not the request — it is the run.
`lease()` pins one endpoint for a run's entire life, which puts every turn of
every agent on the machine that already has the prefix.

That also makes the load balancing honest: runs are the thing there are three
of, so spreading *runs* across three servers is what fills them. Balancing
individual requests would spread each conversation across all three and leave
every cache cold.

Failure is the one case that breaks the pinning: an endpoint that cannot answer
is taken out of rotation for a cooldown and the call is retried elsewhere,
losing the cache but not the run.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .base import LLMRequest, LLMResponse
from .openai_client import EndpointUnavailable, OpenAICompatibleClient

log = logging.getLogger("crew.llm.pool")

COOLDOWN_SECONDS = 30.0


class AllEndpointsDown(RuntimeError):
    """Every server is in cooldown. Says which, and why each one failed."""


@dataclass(slots=True)
class Endpoint:
    client: OpenAICompatibleClient
    leases: int = 0
    failures: int = 0
    down_until: float = 0.0
    last_error: str = ""

    @property
    def url(self) -> str:
        return self.client.base_url

    def healthy(self, now: float) -> bool:
        return now >= self.down_until

    def as_dict(self, now: float) -> dict[str, Any]:
        return {
            "url": self.url,
            "leases": self.leases,
            "failures": self.failures,
            "healthy": self.healthy(now),
            "cooldown_remaining": max(0.0, round(self.down_until - now, 1)),
            "last_error": self.last_error,
        }


class EndpointPool:
    """Routes runs across interchangeable servers of the *same* model.

    Same model on every endpoint is an assumption, not a check: a run whose
    turns landed on different models would produce a mixture nobody could
    reason about, and a benchmark comparing two such runs would be measuring
    the routing. `verify()` reports disagreement rather than hiding it.
    """

    provider = "openai_compatible"

    def __init__(
        self,
        clients: list[OpenAICompatibleClient],
        *,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ) -> None:
        if not clients:
            raise ValueError("an endpoint pool needs at least one server")
        self.endpoints = [Endpoint(client=client) for client in clients]
        self.cooldown_seconds = cooldown_seconds
        self.model = clients[0].model

    @property
    def size(self) -> int:
        return len(self.endpoints)

    async def aclose(self) -> None:
        for endpoint in self.endpoints:
            await endpoint.client.aclose()

    # -- choosing ---------------------------------------------------------

    def _pick(self, exclude: set[str] | None = None) -> Endpoint:
        """The healthy endpoint carrying the fewest runs."""
        now = time.monotonic()
        excluded = exclude or set()
        candidates = [
            e for e in self.endpoints if e.healthy(now) and e.url not in excluded
        ]
        if not candidates:
            # Everything is either in cooldown or already tried for this call.
            # Recovering is better than refusing, so a cooled-down endpoint is
            # preferred over none at all — but only once nothing else is left.
            candidates = [e for e in self.endpoints if e.url not in excluded]
        if not candidates:
            raise AllEndpointsDown(
                "no model server could answer: "
                + "; ".join(f"{e.url} ({e.last_error or 'excluded'})" for e in self.endpoints)
            )
        return min(candidates, key=lambda e: e.leases)

    def _record_failure(self, endpoint: Endpoint, error: Exception) -> None:
        endpoint.failures += 1
        endpoint.last_error = str(error)[:300]
        endpoint.down_until = time.monotonic() + self.cooldown_seconds
        log.warning(
            "endpoint %s out of rotation for %.0fs: %s",
            endpoint.url, self.cooldown_seconds, endpoint.last_error,
        )

    def _record_success(self, endpoint: Endpoint) -> None:
        endpoint.down_until = 0.0
        endpoint.last_error = ""

    # -- using ------------------------------------------------------------

    def lease(self) -> "LeasedEndpoint":
        """Pin one endpoint for the life of a run, keeping its cache warm."""
        endpoint = self._pick()
        endpoint.leases += 1
        log.info("run pinned to %s (%d active)", endpoint.url, endpoint.leases)
        return LeasedEndpoint(self, endpoint)

    def release(self, endpoint: Endpoint) -> None:
        endpoint.leases = max(0, endpoint.leases - 1)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route a single call. Used when the caller did not take a lease.

        Correct, but it gives up the prefix cache across turns — prefer
        `lease()` for anything that will make more than one call.
        """
        _endpoint, response = await self._complete_on(self._pick(), request, tried=set())
        return response

    async def _complete_on(
        self, endpoint: Endpoint, request: LLMRequest, tried: set[str]
    ) -> tuple[Endpoint, LLMResponse]:
        """Try `endpoint`, then every other one, before giving up.

        Returns whichever endpoint actually answered, so a lease can follow the
        work instead of retrying a server it already knows is down.

        Only `EndpointUnavailable` is retried: the request never reached the
        model, so sending it elsewhere cannot repeat an effect. A 4xx is the
        request's own fault and would fail identically everywhere.
        """
        tried = tried | {endpoint.url}
        try:
            response = await endpoint.client.complete(request)
        except EndpointUnavailable as exc:
            self._record_failure(endpoint, exc)
            if len(tried) >= len(self.endpoints):
                raise AllEndpointsDown(
                    "every model server failed this request: "
                    + "; ".join(f"{e.url} ({e.last_error})" for e in self.endpoints)
                ) from exc
            return await self._complete_on(self._pick(exclude=tried), request, tried)
        self._record_success(endpoint)
        return endpoint, response

    # -- reporting --------------------------------------------------------

    def status(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        return [endpoint.as_dict(now) for endpoint in self.endpoints]

    async def verify(self) -> dict[str, Any]:
        """Ask every server which models it serves, and report disagreement.

        A pool of servers running different models silently invalidates every
        comparison made across it, so this is surfaced rather than assumed.
        """
        served: dict[str, list[str]] = {}
        for endpoint in self.endpoints:
            try:
                served[endpoint.url] = await endpoint.client.list_models()
            except Exception as exc:  # noqa: BLE001 - reporting, not controlling
                served[endpoint.url] = []
                endpoint.last_error = str(exc)[:300]
        distinct = {tuple(models) for models in served.values() if models}
        return {
            "served": served,
            "agree": len(distinct) <= 1,
            "configured_model": self.model,
        }


class ModelRouter:
    """Sends each call to the server that runs the model it asked for.

    The pool above balances servers that are interchangeable. This is the other
    case: servers deliberately running *different* models, so that a mechanical
    role can go to a small fast one while the phases that need reasoning keep
    the big one. Nothing is balanced here — the model name decides, and
    `model_for()` is what puts the right name on the request.
    """

    provider = "openai_compatible"

    def __init__(self, default: Any, by_model: dict[str, Any]) -> None:
        self.default = default
        self.by_model = dict(by_model)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await self.by_model.get(request.model, self.default).complete(request)

    async def aclose(self) -> None:
        for client in self.by_model.values():
            await client.aclose()

    def routes(self) -> dict[str, str]:
        return {model: client.base_url for model, client in self.by_model.items()}


@dataclass(slots=True)
class LeasedEndpoint:
    """One run's pinned endpoint. Satisfies the `LLMClient` protocol."""

    pool: EndpointPool
    endpoint: Endpoint
    provider: str = field(default="openai_compatible", init=False)
    _released: bool = field(default=False, init=False)

    @property
    def url(self) -> str:
        return self.endpoint.url

    async def complete(self, request: LLMRequest) -> LLMResponse:
        # Re-pin before calling if this run's server has since gone into
        # cooldown: otherwise every remaining turn would spend one doomed
        # attempt on it before failing over.
        if not self.endpoint.healthy(time.monotonic()):
            self._move_to(self.pool._pick(exclude={self.endpoint.url}))

        served, response = await self.pool._complete_on(self.endpoint, request, tried=set())
        if served is not self.endpoint:
            # A failover moved the work. Follow it, so the rest of the run runs
            # where the conversation now is rather than re-failing every turn.
            self._move_to(served)
        return response

    def _move_to(self, endpoint: Endpoint) -> None:
        if endpoint is self.endpoint:
            return
        self.pool.release(self.endpoint)
        endpoint.leases += 1
        self.endpoint = endpoint
        log.info("run moved to %s", endpoint.url)

    def release(self) -> None:
        """Idempotent: a run that ends twice must not free the slot twice."""
        if self._released:
            return
        self._released = True
        self.pool.release(self.endpoint)
