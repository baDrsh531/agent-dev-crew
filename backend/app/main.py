"""ASGI entry point.

    uvicorn app.main:app --reload --port 8000    (from the backend/ directory)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import get_settings
from .llm.factory import reset_pool
from .orchestrator.service import get_service
from .store.database import get_database
from .workspace.provision import provision

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crew")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    get_database()
    if provision(settings.workspace_root, settings.workspace_template):
        log.info("workspace provisioned from %s", settings.workspace_template)
    log.info(
        "provider=%s approval_mode=%s workspace=%s",
        settings.effective_provider.value,
        settings.approval_mode.value,
        settings.workspace_root,
    )
    if settings.effective_provider.value == "fake":
        log.warning(
            "no ANTHROPIC_API_KEY: running the fake provider. Artifacts will be "
            "schema-valid but semantically empty."
        )
    if len(settings.openai_base_urls) > 1:
        log.info(
            "%d model servers configured; runs are pinned one per server: %s",
            len(settings.openai_base_urls), ", ".join(settings.openai_base_urls),
        )
    yield
    await get_service().shutdown()
    await reset_pool()


app = FastAPI(
    title="Agent Dev Crew",
    version="0.1.0",
    description=(
        "A simulated software team: five specialised agents hand typed artifacts to "
        "one another under a deterministic orchestrator, with per-role tool "
        "permissions and human approval gates."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api")
async def api_root() -> dict[str, str]:
    return {"service": "agent-dev-crew", "docs": "/docs", "health": "/api/health"}


# -- the UI ------------------------------------------------------------------
#
# The built interface is served by this same process, at the same origin. Two
# servers on two ports was an accident of how it was developed, not a design:
# it meant two windows to start, two to stop, one of them able to die without
# anyone noticing, and CORS to configure for a UI that is not actually
# cross-origin. One process serves one app.
#
# Mounted last on purpose. Starlette matches in registration order, so every
# /api route and /docs is already claimed and cannot be shadowed by a file.
UI_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if (UI_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    log.info("serving the UI from %s", UI_DIST)
else:
    log.warning(
        "no built UI at %s — the API is up but there is nothing to open. "
        "Build it with `npm run build` in frontend/, or run `npm run dev` for "
        "hot reload against this API.",
        UI_DIST,
    )

    @app.get("/")
    async def missing_ui() -> dict[str, str]:
        return {
            "service": "agent-dev-crew",
            "ui": "not built — run `npm run build` in frontend/",
            "docs": "/docs",
            "health": "/api/health",
        }
