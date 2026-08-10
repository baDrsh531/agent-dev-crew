"""SQLite persistence.

The event table is the source of truth; `runs` is a projection kept in step
with it so the list view does not have to replay anything. Because every fact
is appended before it is acted on, a run interrupted by a crash or a restart
can be inspected, resumed, or replayed from the log.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain.events import Event, EventType
from ..domain.roles import RunPhase, RunStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    request       TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,
    phase         TEXT NOT NULL,
    branch        TEXT NOT NULL DEFAULT '',
    base_commit   TEXT NOT NULL DEFAULT '',
    worktree_path TEXT NOT NULL DEFAULT '',
    qa_iterations INTEGER NOT NULL DEFAULT 0,
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    error         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    run_id  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    id      TEXT NOT NULL,
    type    TEXT NOT NULL,
    at      TEXT NOT NULL,
    phase   TEXT,
    role    TEXT,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS artifacts (
    run_id     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    iteration  INTEGER NOT NULL DEFAULT 0,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, kind, iteration)
);

CREATE TABLE IF NOT EXISTS approvals (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    tool        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    tool_input  TEXT NOT NULL,
    status      TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_approvals_run ON approvals(run_id, status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created.

        `CREATE TABLE IF NOT EXISTS` does nothing to an existing table, so a
        database from an earlier version would keep working right up until the
        first query naming a new column.
        """
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(runs)")}
        for column, definition in (("worktree_path", "TEXT NOT NULL DEFAULT ''"),):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {definition}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- runs -------------------------------------------------------------

    def create_run(self, run_id: str, request: str, title: str = "") -> dict[str, Any]:
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (id, request, title, status, phase, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    request,
                    title or request[:80],
                    RunStatus.PENDING.value,
                    RunPhase.INTAKE.value,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_run(run_id)  # type: ignore[return-value]

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status", "phase", "branch", "base_commit", "worktree_path",
            "qa_iterations", "tokens_used", "cost_usd", "error", "title",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update unknown run columns: {sorted(unknown)}")
        fields = {
            k: (v.value if hasattr(v, "value") else v) for k, v in fields.items()
        }
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE runs SET {assignments}, updated_at = ? WHERE id = ?",
                (*fields.values(), _now(), run_id),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    # -- events -----------------------------------------------------------

    def append_event(self, evt: Event) -> Event:
        """Assign the next sequence number and persist. Ordering is per run."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS s FROM events WHERE run_id = ?",
                (evt.run_id,),
            ).fetchone()
            evt.seq = int(row["s"]) + 1
            self._conn.execute(
                "INSERT INTO events (run_id, seq, id, type, at, phase, role, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evt.run_id,
                    evt.seq,
                    evt.id,
                    evt.type.value,
                    evt.at.isoformat(),
                    evt.phase.value if evt.phase else None,
                    evt.role.value if evt.role else None,
                    json.dumps(evt.payload, ensure_ascii=False, default=str),
                ),
            )
            self._conn.commit()
        return evt

    def get_events(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
                (run_id, after_seq),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "seq": r["seq"],
                "type": r["type"],
                "at": r["at"],
                "phase": r["phase"],
                "role": r["role"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    # -- artifacts --------------------------------------------------------

    def save_artifact(self, run_id: str, kind: str, payload: dict[str, Any], iteration: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO artifacts (run_id, kind, iteration, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, kind, iteration, json.dumps(payload, ensure_ascii=False, default=str), _now()),
            )
            self._conn.commit()

    def get_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at", (run_id,)
            ).fetchall()
        return [
            {
                "kind": r["kind"],
                "iteration": r["iteration"],
                "payload": json.loads(r["payload"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # -- approvals --------------------------------------------------------

    def create_approval(
        self, approval_id: str, run_id: str, tool: str, summary: str, tool_input: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            self._conn.execute(
                "INSERT INTO approvals (id, run_id, tool, summary, tool_input, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (
                    approval_id,
                    run_id,
                    tool,
                    summary,
                    json.dumps(tool_input, ensure_ascii=False, default=str),
                    _now(),
                ),
            )
            self._conn.commit()
        return self.get_approval(approval_id)  # type: ignore[return-value]

    def resolve_approval(self, approval_id: str, approved: bool, reason: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE approvals SET status = ?, reason = ?, resolved_at = ? WHERE id = ?",
                ("approved" if approved else "denied", reason, _now(), approval_id),
            )
            self._conn.commit()

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["tool_input"] = json.loads(data["tool_input"])
        return data

    def pending_approvals(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND status = 'pending' ORDER BY created_at",
                (run_id,),
            ).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            data["tool_input"] = json.loads(data["tool_input"])
            results.append(data)
        return results


_db: Database | None = None


def get_database(path: Path | None = None) -> Database:
    global _db
    if _db is None:
        from ..config import get_settings

        _db = Database(path or get_settings().database_path)
    return _db


def reset_database() -> None:
    global _db
    if _db is not None:
        _db.close()
    _db = None
