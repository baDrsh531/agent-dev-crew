"""Provider selection and per-role model routing."""

from __future__ import annotations

from typing import Any

from ..config import LLMProvider, Settings, get_settings
from ..domain.roles import AgentRole
from .base import LLMClient, Sampling
from .fake import FakeLLMClient


def build_openai_clients(settings: Settings) -> list[Any]:
    """One transport per configured server, all sharing the model and sampling."""
    from .openai_client import OpenAICompatibleClient

    sampling = Sampling(
        temperature=settings.openai_temperature,
        top_p=settings.openai_top_p,
        top_k=settings.openai_top_k,
        seed=settings.openai_seed,
    )
    return [
        OpenAICompatibleClient(
            base_url=url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            enable_thinking=settings.openai_enable_thinking,
            max_context_tokens=settings.openai_max_context_tokens,
            sampling=sampling,
        )
        for url in settings.openai_base_urls
    ]


def build_role_clients(settings: Settings) -> dict[str, Any]:
    """model name -> its own server, for roles routed off the main one."""
    from .openai_client import OpenAICompatibleClient

    sampling = Sampling(
        temperature=settings.openai_temperature,
        top_p=settings.openai_top_p,
        top_k=settings.openai_top_k,
        seed=settings.openai_seed,
    )
    return {
        model: OpenAICompatibleClient(
            base_url=url,
            model=model,
            api_key=settings.openai_api_key,
            enable_thinking=settings.openai_enable_thinking,
            max_context_tokens=settings.openai_max_context_tokens,
            sampling=sampling,
        )
        for url, model in settings.openai_role_routes.values()
    }


def _wrap_role_routes(settings: Settings, default: Any) -> Any:
    """Put `default` behind a model router when some roles go elsewhere."""
    routes = build_role_clients(settings)
    if not routes:
        return default
    from .pool import ModelRouter

    return ModelRouter(default, routes)


def build_client(settings: Settings | None = None) -> LLMClient:
    """A client for one caller.

    With several servers configured this returns a pool. Note that a pool built
    here is private to its caller, so its load accounting only sees that
    caller's runs — `get_pool()` is what makes the balancing global.
    """
    settings = settings or get_settings()
    provider = settings.effective_provider

    if provider is LLMProvider.FAKE:
        return FakeLLMClient()

    if provider is LLMProvider.OPENAI_COMPATIBLE:
        clients = build_openai_clients(settings)
        if len(clients) > 1:
            from .pool import EndpointPool

            return _wrap_role_routes(settings, EndpointPool(clients))
        return _wrap_role_routes(settings, clients[0])

    from .anthropic_client import AnthropicClient

    return AnthropicClient(api_key=settings.anthropic_api_key)


def lease_client(settings: Settings | None = None) -> tuple[Any | None, Any]:
    """The client one run should use, and how to hand its resources back.

    Composed in one place because the two routing rules interact: a run is
    pinned to one of the interchangeable servers *and* some of its roles are
    sent to a different model entirely. Getting that composition wrong the
    obvious way — leasing, then ignoring the role routes — would silently send
    the documenter to the big model.

    Returns `(None, noop)` when there is nothing to compose, letting the engine
    build its own client as before.
    """
    settings = settings or get_settings()

    def noop() -> None:
        return None

    if settings.effective_provider is not LLMProvider.OPENAI_COMPATIBLE:
        return None, noop

    pool = get_pool(settings)
    lease = pool.lease() if pool is not None else None
    routes = build_role_clients(settings)
    if not routes:
        return lease, (lease.release if lease is not None else noop)

    from .pool import ModelRouter

    router = ModelRouter(lease or build_openai_clients(settings)[0], routes)
    return router, (lease.release if lease is not None else noop)


_pool: Any | None = None


def get_pool(settings: Settings | None = None) -> Any | None:
    """The process-wide pool, or None when only one server is configured.

    Load balancing is only meaningful if every run is counted against the same
    tally, so the pool has to be shared rather than rebuilt per run — three
    private pools would each pick "the least busy server" and all pick the
    first one.
    """
    global _pool
    settings = settings or get_settings()
    if settings.effective_provider is not LLMProvider.OPENAI_COMPATIBLE:
        return None
    if len(settings.openai_base_urls) < 2:
        return None
    if _pool is None:
        from .pool import EndpointPool

        _pool = EndpointPool(build_openai_clients(settings))
    return _pool


async def reset_pool() -> None:
    """Test and shutdown hook: drop the pool and close its transports."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


def model_for(role: AgentRole, settings: Settings | None = None) -> str:
    """Deep reasoning gets the bigger model; mechanical work a cheaper one.

    The returned name is not decoration: it is what `ModelRouter` dispatches
    on, so this is where per-role routing is actually decided. A local setup
    with one server reports that one model for every role — claiming otherwise
    would put a fictional name in the UI and in the cost table.
    """
    settings = settings or get_settings()
    provider = settings.effective_provider

    if provider is LLMProvider.FAKE:
        return "fake"
    if provider is LLMProvider.OPENAI_COMPATIBLE:
        route = settings.openai_role_routes.get(role.value)
        return route[1] if route else settings.openai_model

    return {
        AgentRole.ORCHESTRATOR: settings.model_orchestrator,
        AgentRole.TRANSLATOR: settings.model_translator,
        AgentRole.ANALYST: settings.model_analyst,
        AgentRole.ARCHITECT: settings.model_architect,
        AgentRole.DEVELOPER: settings.model_developer,
        AgentRole.QA: settings.model_qa,
        AgentRole.DOCUMENTER: settings.model_documenter,
    }[role]
