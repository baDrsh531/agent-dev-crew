"""Filesystem tools. Every path goes through the sandbox before it is used."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from ..workspace.sandbox import SandboxViolation
from .base import Tool, ToolContext, ToolResult, obj_schema

MAX_SEARCH_MATCHES = 60
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt")
DOC_DIRECTORIES = ("docs", "doc")


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------


async def _read_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = args["path"]
    try:
        text = ctx.sandbox.read_text(path)
    except SandboxViolation as exc:
        return ToolResult.error(str(exc))
    numbered = "\n".join(
        f"{i:>5}│{line}" for i, line in enumerate(text.splitlines(), start=1)
    )
    return ToolResult(content=numbered or "(empty file)", metadata={"path": path})


async def _list_files(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    pattern = args.get("pattern") or "**/*"
    files = ctx.sandbox.list_files(pattern)
    if not files:
        return ToolResult(content=f"No files match {pattern!r}.")
    return ToolResult(content="\n".join(files), metadata={"count": len(files)})


async def _search_code(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    pattern = args["pattern"]
    glob = args.get("glob") or "**/*"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return ToolResult.error(f"invalid regular expression: {exc}")

    matches: list[str] = []
    for rel in ctx.sandbox.list_files(glob, limit=2000):
        try:
            text = ctx.sandbox.read_text(rel)
        except SandboxViolation:
            continue  # binary, oversized or protected — not an error for a search
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    matches.append(f"... truncated at {MAX_SEARCH_MATCHES} matches")
                    return ToolResult(content="\n".join(matches))
    if not matches:
        return ToolResult(content=f"No match for {pattern!r} in {glob!r}.")
    return ToolResult(content="\n".join(matches), metadata={"count": len(matches)})


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------


async def _write_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path, content = args["path"], args["content"]
    try:
        target = ctx.sandbox.resolve(path)
    except SandboxViolation as exc:
        return ToolResult.error(str(exc))

    existed = target.exists()
    verb = "Overwrite" if existed else "Create"
    approved, reason = await ctx.confirm(
        "write_file",
        f"{verb} {path} ({len(content.splitlines())} lines)",
        {"path": path, "preview": content[:2000]},
    )
    if not approved:
        return ToolResult.error(f"Human declined: {reason}")

    ctx.sandbox.write_text(path, content)
    return ToolResult(
        content=f"{'Overwrote' if existed else 'Created'} {path}.",
        metadata={"path": path, "created": not existed},
    )


async def _edit_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path, old, new = args["path"], args["old_string"], args["new_string"]
    if old == new:
        return ToolResult.error("old_string and new_string are identical.")
    try:
        text = ctx.sandbox.read_text(path)
    except SandboxViolation as exc:
        return ToolResult.error(str(exc))

    occurrences = text.count(old)
    if occurrences == 0:
        return ToolResult.error(
            f"old_string not found in {path}. Read the file again — it may have "
            "changed since you last saw it."
        )
    if occurrences > 1:
        return ToolResult.error(
            f"old_string appears {occurrences} times in {path}; it must be unique. "
            "Include more surrounding context."
        )

    approved, reason = await ctx.confirm(
        "edit_file",
        f"Edit {path} (replace {len(old.splitlines())} lines)",
        {"path": path, "old_string": old[:1000], "new_string": new[:1000]},
    )
    if not approved:
        return ToolResult.error(f"Human declined: {reason}")

    ctx.sandbox.write_text(path, text.replace(old, new, 1))
    return ToolResult(content=f"Edited {path}.", metadata={"path": path})


async def _delete_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = args["path"]
    approved, reason = await ctx.confirm("delete_file", f"Delete {path}", {"path": path})
    if not approved:
        return ToolResult.error(f"Human declined: {reason}")
    try:
        ctx.sandbox.delete(path)
    except SandboxViolation as exc:
        return ToolResult.error(str(exc))
    return ToolResult(content=f"Deleted {path}.", metadata={"path": path})


def _is_documentation(path: str) -> bool:
    p = PurePosixPath(str(path).replace("\\", "/"))
    return p.suffix.lower() in DOC_SUFFIXES or p.parts[:1] in {(d,) for d in DOC_DIRECTORIES}


async def _write_doc(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Same as write_file, but the documenter may only reach documentation paths."""
    path = args["path"]
    if not _is_documentation(path):
        return ToolResult.error(
            f"{path} is not a documentation path. The documentation writer may only "
            f"write {', '.join(DOC_SUFFIXES)} files or files under docs/."
        )
    return await _write_file(ctx, args)


# --------------------------------------------------------------------------

FS_TOOLS: list[Tool] = [
    Tool(
        name="read_file",
        description=(
            "Read a text file from the workspace and return it with line numbers. "
            "Use it before editing a file, and whenever a claim about the code needs "
            "evidence. Paths are workspace-relative."
        ),
        input_schema=obj_schema(
            {"path": {"type": "string", "description": "Workspace-relative file path."}}
        ),
        handler=_read_file,
    ),
    Tool(
        name="list_files",
        description=(
            "List workspace files matching a glob pattern. Call this first to learn "
            "the project layout before guessing at file names."
        ),
        input_schema=obj_schema(
            {
                "pattern": {
                    "type": "string",
                    "description": "Glob, e.g. '**/*.py' or 'src/**/*'. Defaults to '**/*'.",
                }
            },
            required=[],
        ),
        handler=_list_files,
    ),
    Tool(
        name="search_code",
        description=(
            "Search file contents with a Python regular expression and return "
            "`path:line: text` matches. Use it to find where a symbol is defined or "
            "used, instead of reading files one by one."
        ),
        input_schema=obj_schema(
            {
                "pattern": {"type": "string", "description": "Python regular expression."},
                "glob": {
                    "type": "string",
                    "description": "Restrict the search, e.g. '**/*.py'. Defaults to everything.",
                },
            },
            required=["pattern"],
        ),
        handler=_search_code,
    ),
    Tool(
        name="write_file",
        description=(
            "Create a file, or replace its entire contents. Prefer edit_file when "
            "changing part of an existing file. Requires human approval."
        ),
        input_schema=obj_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "content": {"type": "string", "description": "Full file contents."},
            }
        ),
        handler=_write_file,
        mutating=True,
    ),
    Tool(
        name="edit_file",
        description=(
            "Replace one exact, unique occurrence of old_string with new_string. "
            "The match must be unique — include surrounding context to disambiguate. "
            "Requires human approval."
        ),
        input_schema=obj_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace, including indentation.",
                },
                "new_string": {"type": "string", "description": "Replacement text."},
            }
        ),
        handler=_edit_file,
        mutating=True,
    ),
    Tool(
        name="delete_file",
        description="Delete a file from the workspace. Requires human approval.",
        input_schema=obj_schema(
            {"path": {"type": "string", "description": "Workspace-relative file path."}}
        ),
        handler=_delete_file,
        mutating=True,
    ),
    Tool(
        name="write_doc",
        description=(
            "Create or replace a documentation file. Restricted to markdown/text "
            "files and the docs/ directory. Requires human approval."
        ),
        input_schema=obj_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative path ending in .md/.rst/.txt, or under docs/.",
                },
                "content": {"type": "string", "description": "Full file contents."},
            }
        ),
        handler=_write_doc,
        mutating=True,
    ),
]
