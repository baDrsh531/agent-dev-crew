"""A structural map of the workspace, computed once and given to every agent.

The benchmark showed agents spending a large share of their tool budget
rediscovering the same facts: where the files are, what a module defines, which
route lives where. That exploration is deterministic — it does not need a
model, and it does not need to be repeated five times per run.

So the map is built once at run start with `ast` (no model, no tool calls) and
injected into the system prompt, where it also serves as a stable cache prefix.
It is a *map*, not a substitute for reading: it lists what exists and where, and
the agents still open files to see the code.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import Sandbox

MAX_FILES = 200
MAX_SYMBOLS_PER_FILE = 25
MAX_MAP_CHARS = 12_000
SOURCE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb", ".java")

# Files worth calling out by name: they tell an agent how the project is run
# and tested without it having to guess.
NOTABLE = (
    "readme.md", "pyproject.toml", "requirements.txt", "package.json",
    "setup.py", "setup.cfg", "pytest.ini", "tox.ini", "makefile", "dockerfile",
)


@dataclass(slots=True)
class ModuleOutline:
    path: str
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.classes or self.functions or self.routes)


def _decorator_route(node: ast.AST) -> str | None:
    """Recognise `@app.get("/notes")` and friends, which are the real landmarks
    in a web codebase — far more useful to an agent than the handler's name."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            continue
        method = func.attr.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "ROUTE"}:
            continue
        for argument in decorator.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                return f"{method} {argument.value}"
    return None


def outline_python(source: str, path: str) -> ModuleOutline:
    outline = ModuleOutline(path=path)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return outline  # a file mid-edit is not an error worth failing the run for

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            outline.classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            route = _decorator_route(node)
            if route:
                outline.routes.append(route)
            elif not node.name.startswith("_"):
                outline.functions.append(node.name)
    return outline


def build(sandbox: Sandbox) -> str:
    """Render the workspace map. Returns an empty string when there is nothing
    worth saying, so callers can omit the section entirely."""
    files = sandbox.list_files(limit=MAX_FILES * 3)
    if not files:
        return ""

    sources = [f for f in files if Path(f).suffix in SOURCE_SUFFIXES][:MAX_FILES]
    notable = [f for f in files if Path(f).name.lower() in NOTABLE]

    outlines: list[ModuleOutline] = []
    for relative in sources:
        if not relative.endswith(".py"):
            continue
        try:
            source = sandbox.read_text(relative)
        except Exception:  # noqa: BLE001 - unreadable file is not fatal to a map
            continue
        outline = outline_python(source, relative)
        if not outline.is_empty:
            outlines.append(outline)

    lines: list[str] = [
        f"{len(files)} files. Paths are workspace-relative.",
        "",
        "Layout:",
    ]
    lines.extend(f"  {path}" for path in sorted(files)[:MAX_FILES])

    if notable:
        lines += ["", "Project files: " + ", ".join(sorted(notable))]

    if outlines:
        lines += ["", "Python modules:"]
        for outline in outlines:
            parts: list[str] = []
            if outline.routes:
                parts.append("routes " + ", ".join(outline.routes[:MAX_SYMBOLS_PER_FILE]))
            if outline.classes:
                parts.append("classes " + ", ".join(outline.classes[:MAX_SYMBOLS_PER_FILE]))
            if outline.functions:
                parts.append("functions " + ", ".join(outline.functions[:MAX_SYMBOLS_PER_FILE]))
            lines.append(f"  {outline.path}: " + " | ".join(parts))

    rendered = "\n".join(lines)
    if len(rendered) > MAX_MAP_CHARS:
        rendered = rendered[:MAX_MAP_CHARS] + "\n  ... map truncated"
    return rendered
