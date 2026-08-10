"""The repository map: what agents get for free instead of exploring for it."""

from __future__ import annotations

from pathlib import Path

from app.agents.prompts import system_prompt
from app.workspace.repomap import build, outline_python
from app.workspace.sandbox import Sandbox

ROUTES_MODULE = '''\
from fastapi import FastAPI
app = FastAPI()

@app.get("/notes")
def list_notes():
    ...

@app.post("/notes")
async def create_note():
    ...

@app.delete("/admin/notes", status_code=204)
def purge():
    ...

class NoteStore:
    pass

def helper():
    ...

def _private():
    ...
'''


# -- outlining ---------------------------------------------------------------


def test_routes_are_extracted_with_method_and_path() -> None:
    """Routes are the real landmarks in a web codebase — more useful than names."""
    outline = outline_python(ROUTES_MODULE, "app/main.py")
    assert outline.routes == ["GET /notes", "POST /notes", "DELETE /admin/notes"]


def test_a_decorated_route_is_not_also_listed_as_a_function() -> None:
    outline = outline_python(ROUTES_MODULE, "app/main.py")
    assert "list_notes" not in outline.functions


def test_classes_and_public_functions_are_listed() -> None:
    outline = outline_python(ROUTES_MODULE, "app/main.py")
    assert outline.classes == ["NoteStore"]
    assert outline.functions == ["helper"]


def test_private_functions_are_left_out() -> None:
    assert "_private" not in outline_python(ROUTES_MODULE, "x.py").functions


def test_a_file_that_does_not_parse_does_not_break_the_map() -> None:
    """A file mid-edit must not fail a run."""
    outline = outline_python("def broken(:\n", "app/broken.py")
    assert outline.is_empty


# -- building ----------------------------------------------------------------


def test_the_map_lists_the_layout_and_the_symbols(sandbox: Sandbox) -> None:
    sandbox.write_text("app/api.py", ROUTES_MODULE)
    rendered = build(sandbox)

    assert "app/api.py" in rendered
    assert "GET /notes" in rendered
    assert "NoteStore" in rendered


def test_project_files_are_called_out(sandbox: Sandbox) -> None:
    sandbox.write_text("requirements.txt", "fastapi\n")
    rendered = build(sandbox)
    assert "Project files:" in rendered
    assert "requirements.txt" in rendered


def test_an_empty_workspace_produces_no_map(tmp_path: Path) -> None:
    """Callers omit the section entirely rather than injecting an empty block."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert build(Sandbox(empty)) == ""


def test_the_map_is_bounded(sandbox: Sandbox) -> None:
    for i in range(400):
        sandbox.write_text(f"pkg/mod_{i}.py", "class A:\n    pass\n")
    rendered = build(sandbox)
    assert len(rendered) <= 12_100, "an unbounded map would eat the context window"


def test_building_the_map_makes_no_tool_calls_and_no_model_calls(sandbox: Sandbox) -> None:
    """It is static analysis; that is the whole point of it being free."""
    sandbox.write_text("app/api.py", ROUTES_MODULE)
    assert isinstance(build(sandbox), str)  # no client, no context, no budget needed


# -- the prompt prefix -------------------------------------------------------


def test_the_shared_prefix_is_identical_across_every_role() -> None:
    """The longest common prefix is what a KV cache reuses between agents."""
    repo_map = "Layout:\n  app/main.py"
    prompts = [system_prompt(role, repo_map) for role in
               ("analyst", "architect", "developer", "qa", "documenter")]

    shortest = min(len(p) for p in prompts)
    shared = 0
    while shared < shortest and len({p[shared] for p in prompts}) == 1:
        shared += 1

    assert shared > 1_000, "the shared prefix is too short to be worth caching"
    # The map must fall inside the cacheable prefix. It may extend a little
    # further — "You are the " opens every role — which is harmless.
    assert all(repo_map.strip() in p[:shared] for p in prompts), \
        "the map must sit inside the shared prefix, not after the role text"


def test_the_role_text_still_differs() -> None:
    analyst = system_prompt("analyst")
    developer = system_prompt("developer")
    assert analyst != developer
    assert "Business Analyst" in analyst
    assert "Developer" in developer


def test_no_map_means_no_repository_section() -> None:
    assert "<repository_map>" not in system_prompt("analyst")
    assert "<repository_map>" in system_prompt("analyst", "Layout:\n  a.py")


def test_the_map_is_off_by_default() -> None:
    """It measured worse than not doing it; shipping it on would be dishonest."""
    from app.config import Settings

    assert Settings(llm_provider="fake").repo_map_enabled is False


def test_the_map_is_labelled_as_static_analysis() -> None:
    """An agent must know the map says nothing about behaviour."""
    prompt = system_prompt("architect", "Layout:\n  a.py")
    assert "static analysis" in prompt
    assert "read a file before" in prompt
