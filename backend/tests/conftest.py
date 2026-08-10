"""Test fixtures.

Every test runs against the fake provider and a throwaway git workspace, so
the suite is offline, deterministic and free.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import ApprovalMode, LLMProvider, Settings  # noqa: E402
from app.domain.artifacts import (  # noqa: E402
    ChangeSet, DocsBundle, IntakeBrief, Plan, QAReport, Spec,
)
from app.llm.base import LLMRequest, LLMResponse, Usage  # noqa: E402
from app.store.broker import EventBroker  # noqa: E402
from app.store.database import Database  # noqa: E402
from app.workspace.sandbox import Sandbox  # noqa: E402

ARTIFACT_BY_TITLE = {
    "IntakeBrief": IntakeBrief, "Spec": Spec, "Plan": Plan, "ChangeSet": ChangeSet,
    "QAReport": QAReport, "DocsBundle": DocsBundle,
}


class RoleScriptedClient:
    """Answers each agent with a pre-built artifact, chosen by output schema.

    Keying on the requested schema rather than call order means a test does not
    break when the orchestrator gains or reorders a tool call.
    """

    provider = "fake"

    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        title = (request.output_format or {}).get("schema", {}).get("title", "")
        queue = self.responses.get(title)
        if not queue:
            raise AssertionError(f"no scripted response left for schema {title!r}")
        artifact = queue.pop(0) if len(queue) > 1 else queue[0]
        return LLMResponse(
            content=[{"type": "text", "text": artifact.model_dump_json()}],
            stop_reason="end_turn",
            usage=Usage(input_tokens=100, output_tokens=50),
            model="fake",
        )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    return root


@pytest.fixture
def sandbox(workspace: Path) -> Sandbox:
    return Sandbox(workspace)


@pytest.fixture
def settings(workspace: Path, tmp_path: Path) -> Settings:
    return Settings(
        anthropic_api_key="",
        llm_provider=LLMProvider.FAKE,
        workspace_root=workspace,
        database_path=tmp_path / "test.db",
        approval_mode=ApprovalMode.AUTO,
        max_qa_iterations=2,
        max_tokens_per_run=1_000_000,
        max_wall_clock_seconds=120,
        max_tool_calls_per_agent=10,
    )


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "events.db")
    yield database
    database.close()


@pytest.fixture
def broker() -> EventBroker:
    return EventBroker()


# -- artifact builders -------------------------------------------------------


def make_spec() -> Spec:
    return Spec(
        summary="Protect write routes with JWT.",
        user_stories=[
            {
                "id": "US-1",
                "as_a": "an API client",
                "i_want": "to authenticate with a token",
                "so_that": "I can create notes",
                "acceptance_criteria": ["POST /notes without a token returns 401"],
            }
        ],
        out_of_scope=["refresh tokens"],
        open_questions=[],
        assumptions=["HS256 is acceptable"],
    )


def make_plan() -> Plan:
    return Plan(
        approach="Add a FastAPI dependency that validates a bearer token.",
        alternatives_rejected=["Middleware — too coarse to exempt public routes."],
        steps=[
            {
                "id": "S-1",
                "action": "create",
                "target": "app/auth.py",
                "intent": "Token creation and validation helpers.",
                "rationale": "Keeps auth logic out of the route module.",
                "depends_on": [],
                "covers": ["US-1"],
            }
        ],
        risks=[{"description": "Secret in source", "severity": "high", "mitigation": "Read from env."}],
        verification_strategy="Run pytest; add a test asserting 401 without a token.",
    )


def make_changeset() -> ChangeSet:
    return ChangeSet(
        summary="Added JWT auth.",
        files_changed=[{"path": "app/auth.py", "action": "create", "summary": "Token helpers."}],
        commands_run=["python -m pytest -q"],
        steps_completed=["S-1"],
        steps_skipped=[],
        skip_reasons=[],
        notes_for_qa="Secret is read from JWT_SECRET.",
    )


def make_qa_report(verdict: str = "pass") -> QAReport:
    findings = (
        []
        if verdict == "pass"
        else [
            {
                "severity": "high",
                "file": "app/auth.py",
                "line": 12,
                "summary": "Token expiry is not checked.",
                "failure_scenario": "A token issued yesterday is still accepted today.",
                "suggested_fix": "Verify the exp claim.",
            }
        ]
    )
    return QAReport(
        verdict=verdict,
        checks=[{"name": "pytest", "passed": verdict == "pass", "detail": "7 passed"}],
        findings=findings,
        uncovered_stories=[],
        summary=f"Verdict: {verdict}.",
    )


def make_docs() -> DocsBundle:
    return DocsBundle(
        changelog_entry="### Added\n- JWT authentication on write routes.",
        api_documentation="",
        usage_examples="",
        setup_instructions="Set JWT_SECRET.",
        summary_for_humans="Write routes now require a bearer token.",
        plain_language_diff=(
            "Creating or changing a note now requires signing in. Reading notes still "
            "works for everyone, exactly as before."
        ),
        report={
            "what_changed": "People must now sign in before they can add or edit a note.",
            "what_was_verified": "The existing seven checks still pass, plus new ones "
            "covering signed-in and signed-out access.",
            "what_to_watch": "The signing key is read from an environment variable and "
            "must be set before going live.",
        },
    )


def make_intake() -> IntakeBrief:
    return IntakeBrief(
        understood_goal="Si j'ai bien compris, tu veux que seules les personnes "
        "identifiées puissent modifier les notes.",
        proposed_steps=[
            "Ajouter une façon de se connecter.",
            "Empêcher la modification sans connexion.",
            "Réserver l'effacement total aux administrateurs.",
        ],
        clarifications=[
            {
                "question": "Est-ce que tout le monde peut encore lire les notes ?",
                "assumed_answer": "Oui, la lecture reste ouverte à tous.",
                "why_it_matters": "Si la lecture doit aussi être protégée, le travail est plus large.",
            }
        ],
        out_of_scope=["Créer des comptes utilisateurs."],
        risk_note="Réversible : tout le travail se fait sur une branche séparée.",
        technical_request="Add JWT bearer authentication: GET routes public, write "
        "routes require a valid token, /admin/* requires the admin role.",
    )
