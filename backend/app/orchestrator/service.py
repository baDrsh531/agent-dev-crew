"""Run registry: owns the live engines and the tasks driving them."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from ..config import ApprovalMode, Settings, get_settings
from ..domain.roles import TERMINAL_STATUSES, RunPhase, RunStatus
from ..llm.factory import lease_client
from ..llm.replay import ReplayLLMClient
from ..store.broker import EventBroker, get_broker
from ..store.database import Database, get_database
from ..workspace.preflight import assert_ready
from ..workspace.provision import provision
from ..workspace.sandbox import BLOCKED_SEGMENTS, Sandbox, SandboxViolation
from ..workspace.worktree import Worktree, WorktreeError
from ..workspace.worktree import create as create_worktree
from .engine import MAX_DIFF_CHARS, RunEngine
from .resume import ResumeState

log = logging.getLogger("crew.service")

# A new file that has never been added is invisible to `git diff`, so a run
# whose whole contribution was creating files showed an empty diff. Rendering
# them as ordinary additions is the honest thing; the alternative — `git add
# --intent-to-add` — would mutate a live run's index from a GET request.
MAX_NEW_FILE_LINES = 400


def _last_budget(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The run's final budget, read back from its own event log.

    It used to come from the live engine, so every run from a previous process
    reported no budget at all — and the UI, reading `budget.tokens_used`, showed
    a completed 400k-token run as having used zero. The ceilings went with it,
    which is worse: the gauges silently had nothing to measure against.

    The log already holds it. `budget.updated` is appended as the run goes, so
    the last one is the final state — no second source, and it survives a
    restart because the event store is the source of truth.
    """
    for event in reversed(events):
        if event.get("type") == "budget.updated":
            payload = event.get("payload")
            if isinstance(payload, dict):
                return payload
    return None


def _untracked_diff(sandbox: Sandbox) -> str:
    """Unified-diff blocks for files git does not track yet."""
    listing = sandbox.git("ls-files", "--others", "--exclude-standard")
    if listing.returncode != 0:
        return ""

    blocks: list[str] = []
    for name in listing.stdout.splitlines():
        name = name.strip()
        if not name:
            continue
        # `.env` and friends are refused by the sandbox, so an untracked one
        # here would raise rather than be skipped — and take the whole diff,
        # and the workspace tree that calls it, down with it. They are also
        # exactly what must never be echoed into a diff, so skip them first.
        if BLOCKED_SEGMENTS.intersection(Path(name).parts):
            continue
        try:
            path = sandbox.resolve(name)
            content = path.read_text(encoding="utf-8")
        except (OSError, ValueError, SandboxViolation):  # UnicodeDecodeError is a ValueError
            # Binary, unreadable, or refused: named, not guessed at.
            blocks.append(f"diff --git a/{name} b/{name}\nnew file\nBinary files differ\n")
            continue

        lines = content.splitlines()
        clipped = lines[:MAX_NEW_FILE_LINES]
        body = "".join(f"+{line}\n" for line in clipped)
        if len(lines) > len(clipped):
            body += f"+... [{len(lines) - len(clipped)} more lines]\n"
        blocks.append(
            f"diff --git a/{name} b/{name}\n"
            f"new file mode 100644\n--- /dev/null\n+++ b/{name}\n"
            f"@@ -0,0 +1,{len(clipped)} @@\n{body}"
        )
    return "".join(blocks)


class RunService:
    def __init__(
        self,
        settings: Settings | None = None,
        db: Database | None = None,
        broker: EventBroker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = db or get_database()
        self.broker = broker or get_broker()
        self._engines: dict[str, RunEngine] = {}
        self._tasks: dict[str, asyncio.Task[RunStatus]] = {}

    def start_run(
        self,
        request: str,
        title: str = "",
        approval_mode: ApprovalMode | None = None,
        max_tokens: int | None = None,
    ) -> str:
        # Cheap no-op when the workspace already exists; recreates it if a reset
        # or a manual delete left nothing behind.
        provision(self.settings.workspace_root, self.settings.workspace_template)
        # Refuse before branching rather than discovering the problem mid-run.
        assert_ready(self.settings)
        run_id = uuid.uuid4().hex
        self.db.create_run(run_id, request, title)
        # Autonomy is per run: the same person wants a tight leash on an
        # unfamiliar project and a loose one on a scratch branch.
        # Both are per run. A ceiling in particular has to be: the whole point
        # of an escalation is that it tells you what was missing, and acting on
        # that should not mean editing .env and restarting.
        overrides: dict[str, Any] = {}
        if approval_mode is not None:
            overrides["approval_mode"] = approval_mode
        if max_tokens is not None:
            overrides["max_tokens_per_run"] = max_tokens
        settings = self.settings.model_copy(update=overrides) if overrides else self.settings
        worktree = self._checkout_for(run_id, request)
        client, release = self._lease()
        engine = RunEngine(
            run_id,
            request,
            settings=settings,
            sandbox=Sandbox(worktree.path if worktree else settings.workspace_root),
            llm=client,
            db=self.db,
            broker=self.broker,
            worktree=worktree,
        )
        self._engines[run_id] = engine
        self._spawn(run_id, engine, release, prefix="run")
        return run_id

    # -- model servers ----------------------------------------------------

    def _lease(self) -> tuple[Any | None, Any]:
        """The client this run should use, and how to hand it back.

        Pinning rather than balancing per request is deliberate: a local server
        caches the prompt prefix, and every turn of a run shares all but its
        tail with the previous one.
        """
        return lease_client(self.settings)

    def _spawn(
        self, run_id: str, engine: RunEngine, release: Any, *, prefix: str
    ) -> asyncio.Task[RunStatus]:
        """Drive the engine, and free its server slot however the run ends."""
        task = asyncio.create_task(engine.run(), name=f"{prefix}-{run_id[:8]}")

        def done(_task: asyncio.Task[RunStatus], rid: str = run_id) -> None:
            self._tasks.pop(rid, None)
            release()

        task.add_done_callback(done)
        self._tasks[run_id] = task
        return task

    # -- per-run checkouts ------------------------------------------------

    def _checkout_for(self, run_id: str, request: str) -> Worktree | None:
        """Give the run its own checkout, or None to share `workspace_root`.

        Failure is raised rather than quietly downgraded: falling back to the
        shared tree would let two runs edit the same files while the UI still
        claimed they were isolated.
        """
        if not self.settings.use_worktrees:
            return None
        worktree = create_worktree(self.settings.workspace_root, run_id, request)
        self.db.update_run(
            run_id,
            branch=worktree.branch,
            base_commit=worktree.base_commit,
            worktree_path=str(worktree.path),
        )
        return worktree

    def _recorded_checkout(self, record: dict[str, Any]) -> Worktree | None:
        """Rebuild the handle for a run's checkout from what was persisted.

        Survives a restart: the branch and the path are columns, not state held
        by a live engine.
        """
        path = record.get("worktree_path") or ""
        if not path:
            return None
        return Worktree(
            path=Path(path),
            branch=record["branch"],
            base_commit=record["base_commit"],
            base_repo=self.settings.workspace_root,
        )

    def diff(self, run_id: str) -> dict[str, Any]:
        """What a run changed, live or long finished.

        Deliberately not "ask the engine": engines only exist while the process
        that created them does, so after a restart the diff of every past run
        vanished — exactly the runs someone is most likely to be reviewing. The
        branch and the base commit are persisted columns, so the diff can be
        recomputed from git instead of remembered in memory.
        """
        record = self.db.get_run(run_id)
        if record is None:
            raise LookupError(f"unknown run {run_id}")

        base_commit = record.get("base_commit") or ""
        checkout = Path(record.get("worktree_path") or self.settings.workspace_root)
        branch = record.get("branch") or ""

        if not base_commit:
            return {"diff": "", "branch": branch, "available": False,
                    "reason": "this run never reached the point of branching"}
        if not checkout.is_dir():
            return {"diff": "", "branch": branch, "available": False,
                    "reason": f"the run's checkout is gone ({checkout})"}

        sandbox = Sandbox(checkout)
        if not sandbox.is_git_repo():
            return {"diff": "", "branch": branch, "available": False,
                    "reason": f"{checkout} is not a git repository"}

        result = sandbox.git("diff", base_commit, "--", ".")
        if result.returncode != 0:
            return {"diff": "", "branch": branch, "available": False,
                    "reason": result.stderr.strip()[:300] or "git could not produce a diff"}

        text = result.stdout + _untracked_diff(sandbox)
        truncated = len(text) > MAX_DIFF_CHARS
        return {
            "diff": text[:MAX_DIFF_CHARS] if truncated else text,
            "branch": branch,
            "base_commit": base_commit,
            "available": True,
            "truncated": truncated,
        }

    def workspace(self, run_id: str) -> dict[str, Any]:
        """The files a run can see, and which ones it touched.

        Listed through the Sandbox rather than by walking the directory, so the
        view shows exactly what the agents were allowed to reach — `.git`,
        `.env` and the rest are absent here for the same reason they are absent
        to a tool call. A file tree that showed more than the agents can see
        would misrepresent the containment it exists to make visible.
        """
        record = self.db.get_run(run_id)
        if record is None:
            raise LookupError(f"unknown run {run_id}")

        checkout = Path(record.get("worktree_path") or self.settings.workspace_root)
        if not checkout.is_dir():
            return {"root": str(checkout), "available": False,
                    "reason": "the run's checkout is gone", "files": []}

        sandbox = Sandbox(checkout)
        touched: set[str] = set()
        diff = self.diff(run_id)
        if diff.get("available"):
            for line in diff["diff"].splitlines():
                if line.startswith("diff --git "):
                    touched.add(line.split(" b/", 1)[-1].strip())

        return {
            "root": str(checkout),
            "available": True,
            "branch": record.get("branch", ""),
            "files": [
                {"path": path, "touched": path in touched}
                for path in sandbox.list_files()
            ],
            "blocked": sorted(BLOCKED_SEGMENTS),
        }

    def rollback(self, run_id: str) -> dict[str, Any]:
        """Discard everything a run produced: its checkout and its branch.

        Only possible because the run never shared a working tree — there is
        nothing to untangle from anyone else's work, so undo is a delete.
        """
        record = self.db.get_run(run_id)
        if record is None:
            raise LookupError(f"unknown run {run_id}")
        if run_id in self._tasks:
            raise ValueError(f"run {run_id} is still running — cancel it first")

        worktree = self._recorded_checkout(record)
        if worktree is None:
            raise ValueError(
                f"run {run_id} did not work in its own checkout; "
                "there is nothing that can be discarded without touching other runs"
            )
        worktree.remove()
        self.db.update_run(run_id, worktree_path="")
        self._engines.pop(run_id, None)
        return {"run_id": run_id, "branch": worktree.branch, "removed": str(worktree.path)}

    def discard_all_checkouts(self) -> int:
        """Remove every recorded checkout. Returns how many were removed.

        Resetting the workspace deletes the base repository's `.git`, which
        would strand each worktree as a directory belonging to no repository —
        unremovable through git, and still recorded against its run. So they go
        first, while they are still attached to something.
        """
        removed = 0
        for record in self.db.list_runs(limit=1000):
            worktree = self._recorded_checkout(record)
            if worktree is None:
                continue
            try:
                worktree.remove()
            except (OSError, WorktreeError):
                log.warning("could not remove the checkout for run %s", record["id"][:8])
                continue
            self.db.update_run(record["id"], worktree_path="")
            removed += 1
        return removed

    def resume_run(self, run_id: str) -> str:
        """Continue an interrupted run from the phase it did not finish.

        The resume point is derived from the artifacts, so a crash between two
        phases costs only the phase that was in flight.
        """
        record = self.db.get_run(run_id)
        if record is None:
            raise LookupError(f"unknown run {run_id}")
        if record["status"] in {s.value for s in TERMINAL_STATUSES if s is not RunStatus.CANCELLED}:
            raise ValueError(f"run {run_id} already finished as {record['status']}")
        if run_id in self._tasks:
            raise ValueError(f"run {run_id} is still running")

        state = ResumeState.load(self.db, run_id)
        if state.next_phase is RunPhase.DONE:
            raise ValueError(f"run {run_id} has nothing left to do")

        # Rejoin the run's own checkout when it had one; its branch is already
        # checked out there, so resuming does not have to switch anything.
        worktree = self._recorded_checkout(record)
        if worktree is not None and not worktree.path.is_dir():
            raise ValueError(
                f"run {run_id} cannot resume: its checkout at {worktree.path} is gone"
            )
        client, release = self._lease()
        engine = RunEngine(
            run_id, record["request"],
            settings=self.settings,
            sandbox=Sandbox(worktree.path if worktree else self.settings.workspace_root),
            llm=client,
            db=self.db, broker=self.broker, resume=state, worktree=worktree,
        )
        self._engines[run_id] = engine
        self._spawn(run_id, engine, release, prefix="resume")
        return run_id

    def replay_run(self, source_run_id: str) -> str:
        """Re-execute a recorded run's orchestration without calling a model.

        Verifies the *state machine*, not the file effects: the replay provider
        returns each recorded artifact directly, so no tool calls are made and
        the workspace is untouched. Use it to check that a change to the
        orchestration still drives a real run to the same outcome.
        """
        record = self.db.get_run(source_run_id)
        if record is None:
            raise LookupError(f"unknown run {source_run_id}")
        client = ReplayLLMClient(self.db, source_run_id)
        if not client.recorded:
            raise ValueError(f"run {source_run_id} recorded no artifacts to replay")

        replay_id = uuid.uuid4().hex
        self.db.create_run(replay_id, record["request"], title=f"replay of {source_run_id[:8]}")
        # A replay makes no tool calls, but it still gets its own checkout so
        # that re-running the state machine can never move the base repository.
        worktree = self._checkout_for(replay_id, record["request"])
        engine = RunEngine(
            replay_id, record["request"],
            settings=self.settings.model_copy(update={"approval_mode": ApprovalMode.AUTO}),
            sandbox=Sandbox(worktree.path if worktree else self.settings.workspace_root),
            llm=client, db=self.db, broker=self.broker, worktree=worktree,
        )
        self._engines[replay_id] = engine
        # No lease: a replay calls no model, so it must not hold a server slot.
        self._spawn(replay_id, engine, lambda: None, prefix="replay")
        return replay_id

    def resumable(self, run_id: str) -> dict[str, Any] | None:
        record = self.db.get_run(run_id)
        if record is None:
            return None
        state = ResumeState.load(self.db, run_id)
        return {
            "resumable": (
                run_id not in self._tasks
                and state.next_phase is not RunPhase.DONE
                and record["status"] not in {
                    RunStatus.SUCCEEDED.value, RunStatus.FAILED.value,
                }
            ),
            "next_phase": state.next_phase.value,
            "completed": [
                kind for kind, value in (
                    ("spec", state.spec), ("plan", state.plan),
                    ("changeset", state.changeset), ("qa_report", state.report),
                    ("docs_bundle", state.docs),
                ) if value is not None
            ],
            "branch": state.branch,
        }

    def engine(self, run_id: str) -> RunEngine | None:
        return self._engines.get(run_id)

    def resolve_approval(self, run_id: str, approval_id: str, approved: bool, reason: str = "") -> bool:
        engine = self._engines.get(run_id)
        if engine is None:
            return False
        return engine.resolve_approval(approval_id, approved, reason)

    def cancel(self, run_id: str) -> bool:
        engine = self._engines.get(run_id)
        if engine is None:
            return False
        engine.cancel()
        return True

    async def shutdown(self) -> None:
        for engine in self._engines.values():
            engine.cancel()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def snapshot(self, run_id: str) -> dict[str, Any] | None:
        """Everything a freshly-opened UI needs to render a run."""
        run = self.db.get_run(run_id)
        if run is None:
            return None
        engine = self._engines.get(run_id)
        events = self.db.get_events(run_id)
        return {
            "run": run,
            "events": events,
            "artifacts": self.db.get_artifacts(run_id),
            "pending_approvals": self.db.pending_approvals(run_id),
            "live": engine is not None and run["status"] not in {
                RunStatus.SUCCEEDED.value, RunStatus.FAILED.value,
                RunStatus.ESCALATED.value, RunStatus.CANCELLED.value,
            },
            "budget": engine.budget.as_dict() if engine else _last_budget(events),
        }


_service: RunService | None = None


def get_service() -> RunService:
    global _service
    if _service is None:
        _service = RunService()
    return _service


def reset_service() -> None:
    global _service
    _service = None
