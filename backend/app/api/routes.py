"""HTTP surface.

The UI is a projection of the event log, so the API is deliberately thin:
create a run, subscribe to its events, answer approval requests, read
artifacts. The SSE endpoint replays from `after_seq` before tailing, so a
reconnecting client never loses the events emitted while it was away.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..config import ApprovalMode, get_settings
from ..domain.roles import AgentRole, RunPhase
from ..llm.factory import get_pool, model_for
from ..orchestrator.service import get_service
from ..store.database import get_database
from ..tools.registry import permission_matrix
from ..workspace.preflight import PreflightFailed
from ..workspace.preflight import check as preflight_check
from ..workspace.provision import provision
from ..workspace.sandbox import Sandbox, SandboxViolation

router = APIRouter(prefix="/api")

HEARTBEAT_SECONDS = 15
RUN_NOT_FOUND = "run not found"


class CreateRunRequest(BaseModel):
    request: str = Field(min_length=8, description="What the crew should build.")
    title: str = ""
    approval_mode: ApprovalMode | None = Field(
        default=None,
        description="How much this run asks before acting. Per run, not global: "
        "the same person wants a tight leash on an unfamiliar project and a "
        "loose one on a scratch branch. Falls back to the configured default.",
    )
    max_tokens: int | None = Field(
        default=None, ge=10_000, le=4_000_000,
        description="Token ceiling for this run only. Exists so that a run "
        "which escalated on the budget can be relaunched with more room "
        "without editing .env — the escalation says what was missing, and "
        "acting on it should not mean restarting the server.",
    )


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""


@router.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    try:
        sandbox = Sandbox(settings.workspace_root)
        workspace = {
            "root": str(sandbox.root),
            "is_git_repo": sandbox.is_git_repo(),
            "branch": sandbox.current_branch() if sandbox.is_git_repo() else "",
            "clean": sandbox.is_clean() if sandbox.is_git_repo() else True,
        }
    except SandboxViolation as exc:
        workspace = {"error": str(exc)}
    pool = get_pool(settings)
    return {
        "status": "ok",
        "provider": settings.effective_provider.value,
        "approval_mode": settings.approval_mode.value,
        "workspace": workspace,
        "endpoints": pool.status() if pool is not None else [],
    }


@router.get("/health/endpoints")
async def endpoint_health() -> dict[str, Any]:
    """Per-server state, and whether they actually serve the same model.

    Worth its own call because it reaches out over the network: a pool whose
    servers disagree invalidates every comparison made across it, so the
    disagreement is reported rather than assumed away.
    """
    settings = get_settings()
    # Roles sent to a different model entirely: reported separately because
    # those servers are *meant* to disagree, and folding them into the
    # agreement check would turn a deliberate choice into a warning.
    role_routes = {
        role: {"url": url, "model": model}
        for role, (url, model) in settings.openai_role_routes.items()
    }
    pool = get_pool(settings)
    if pool is None:
        return {"pooled": False, "endpoints": [], "agree": True, "role_routes": role_routes}
    verification = await pool.verify()
    return {
        "pooled": True, "endpoints": pool.status(), "role_routes": role_routes, **verification
    }


@router.get("/config")
async def config() -> dict[str, Any]:
    """Everything the UI needs to explain the system to a viewer."""
    settings = get_settings()
    return {
        "provider": settings.effective_provider.value,
        "approval_mode": settings.approval_mode.value,
        "approval_modes": [
            {"id": mode.value, "label": mode.label} for mode in ApprovalMode
        ],
        "limits": {
            "max_qa_iterations": settings.max_qa_iterations,
            "max_tokens_per_run": settings.max_tokens_per_run,
            "max_wall_clock_seconds": settings.max_wall_clock_seconds,
            "max_tool_calls_per_agent": settings.max_tool_calls_per_agent,
        },
        "roles": [
            {
                "id": role.value,
                "label": role.label,
                "model": model_for(role, settings),
            }
            for role in AgentRole
        ],
        "phases": [phase.value for phase in RunPhase],
        "permissions": permission_matrix(),
    }


@router.post("/workspace/reset")
async def reset_workspace() -> dict[str, Any]:
    """Throw the scratch workspace away and re-copy the template.

    Refused while a run is live — resetting the filesystem under a working
    agent would corrupt it rather than help.
    """
    settings = get_settings()
    service = get_service()
    if any(
        run["status"] in {"running", "pending", "waiting_for_human"}
        for run in get_database().list_runs(20)
        if service.engine(run["id"]) is not None
    ):
        raise HTTPException(status_code=409, detail="a run is still in progress")
    if settings.workspace_template is None:
        raise HTTPException(
            status_code=400,
            detail="no workspace template configured; nothing to reset to",
        )
    # Before the base repository's .git goes, so no checkout is left orphaned.
    discarded = service.discard_all_checkouts()
    provision(settings.workspace_root, settings.workspace_template, force=True)
    return {
        "ok": True,
        "workspace": str(settings.workspace_root),
        "checkouts_discarded": discarded,
    }


@router.get("/workspace/preflight")
async def workspace_preflight() -> dict[str, Any]:
    """Whether a run may start, and precisely what to fix if not."""
    settings = get_settings()
    issues = preflight_check(settings)
    return {
        "ready": not any(i.blocking for i in issues),
        "managed": settings.workspace_template is not None,
        "workspace": str(settings.workspace_root),
        "issues": [i.as_dict() for i in issues],
    }


@router.post("/runs", status_code=201)
async def create_run(body: CreateRunRequest) -> dict[str, Any]:
    service = get_service()
    try:
        run_id = service.start_run(
            body.request, body.title,
            approval_mode=body.approval_mode, max_tokens=body.max_tokens,
        )
    except PreflightFailed as exc:
        # 409, not 500: the request is fine, the workspace is not ready.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "workspace is not ready",
                "issues": [i.as_dict() for i in exc.issues],
            },
        ) from exc
    return {"run_id": run_id}


@router.get("/runs")
async def list_runs(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    return {"runs": get_database().list_runs(limit)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    snapshot = get_service().snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    return snapshot


@router.get("/runs/{run_id}/events")
async def get_events(run_id: str, after_seq: int = Query(0, ge=0)) -> dict[str, Any]:
    if get_database().get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    return {"events": get_database().get_events(run_id, after_seq)}


@router.get("/runs/{run_id}/diff")
async def get_diff(run_id: str) -> dict[str, Any]:
    """What the run changed, recomputed from git rather than held in memory.

    `available: false` with a reason, never a bare 404 for a run that exists:
    "no diff yet" and "no such run" are different answers and the UI has to
    say which.
    """
    try:
        return get_service().diff(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/approvals/{approval_id}")
async def resolve_approval(
    run_id: str, approval_id: str, decision: ApprovalDecision
) -> dict[str, Any]:
    approval = get_database().get_approval(approval_id)
    if approval is None or approval["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="approval not found")
    if approval["status"] != "pending":
        raise HTTPException(
            status_code=409, detail=f"approval already {approval['status']}"
        )
    if not get_service().resolve_approval(run_id, approval_id, decision.approved, decision.reason):
        raise HTTPException(status_code=409, detail="run is no longer waiting on this approval")
    return {"ok": True}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    if not get_service().cancel(run_id):
        raise HTTPException(status_code=404, detail="run is not running")
    return {"ok": True}


@router.get("/runs/{run_id}/resumable")
async def resumable(run_id: str) -> dict[str, Any]:
    state = get_service().resumable(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    return state


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str) -> dict[str, Any]:
    """Continue an interrupted run from the phase it did not finish."""
    try:
        get_service().resume_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "run_id": run_id}


@router.post("/runs/{run_id}/replay")
async def replay_run(run_id: str) -> dict[str, Any]:
    """Re-drive the orchestration on a recorded run's artifacts. No model call."""
    try:
        replay_id = get_service().replay_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "run_id": replay_id, "replay_of": run_id}


@router.get("/runs/{run_id}/workspace")
async def get_workspace(run_id: str) -> dict[str, Any]:
    """The run's file tree, as the agents were allowed to see it."""
    try:
        return get_service().workspace(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/rollback")
async def rollback_run(run_id: str) -> dict[str, Any]:
    """Discard a run entirely: its checkout and its branch both go.

    Safe because the run never shared a working tree with any other run, so
    nothing has to be untangled — undo is a delete.
    """
    try:
        return {"ok": True, **get_service().rollback(run_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/stream")
async def stream(run_id: str, request: Request, after_seq: int = Query(0, ge=0)):
    db = get_database()
    if db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)

    service = get_service()
    broker = service.broker
    queue = await broker.subscribe(run_id)

    async def generator():
        try:
            # Backfill first, then tail. Events that arrive during the backfill
            # are already buffered in the queue and deduplicated by seq.
            seen = after_seq
            for evt in db.get_events(run_id, after_seq):
                seen = max(seen, evt["seq"])
                yield {"event": "run", "data": json.dumps(evt, default=str)}

            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if evt.get("seq", 0) <= seen:
                    continue
                seen = evt["seq"]
                yield {"event": "run", "data": json.dumps(evt, default=str)}
        finally:
            await broker.unsubscribe(run_id, queue)

    return EventSourceResponse(generator())
