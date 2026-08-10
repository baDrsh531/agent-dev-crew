"""Version-control tools.

Git is the undo button for the whole system: the run works on a dedicated
branch, commits step by step, and a bad run is discarded with a reset rather
than by hand-repairing files.
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult, obj_schema

MAX_DIFF_CHARS = 20_000


async def _git_diff(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if not ctx.sandbox.is_git_repo():
        return ToolResult.error("workspace is not a git repository")
    unstaged = ctx.sandbox.diff()
    staged = ctx.sandbox.diff(staged=True)
    combined = "\n".join(part for part in (staged, unstaged) if part.strip())
    if not combined.strip():
        return ToolResult(content="No changes in the working tree.")
    if len(combined) > MAX_DIFF_CHARS:
        combined = combined[:MAX_DIFF_CHARS] + "\n... [diff truncated]"
    return ToolResult(content=combined)


async def _git_commit(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    message = args["message"].strip()
    if not message:
        return ToolResult.error("commit message is empty")
    if not ctx.sandbox.is_git_repo():
        return ToolResult.error("workspace is not a git repository")
    if ctx.sandbox.is_clean():
        return ToolResult(content="Nothing to commit — working tree is clean.")

    approved, reason = await ctx.confirm(
        "git_commit", f"Commit: {message.splitlines()[0]}", {"message": message}
    )
    if not approved:
        return ToolResult.error(f"Human declined: {reason}")

    add = ctx.sandbox.git("add", "-A")
    if add.returncode != 0:
        return ToolResult.error(f"git add failed: {add.stderr.strip()}")
    commit = ctx.sandbox.git("commit", "-m", message)
    if commit.returncode != 0:
        return ToolResult.error(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")

    sha = ctx.sandbox.git("rev-parse", "--short", "HEAD").stdout.strip()
    return ToolResult(content=f"Committed {sha}: {message}", metadata={"sha": sha})


VCS_TOOLS: list[Tool] = [
    Tool(
        name="git_diff",
        description=(
            "Show the working-tree diff for the run's branch. Use it to review what "
            "actually changed rather than trusting a summary of it."
        ),
        input_schema=obj_schema({}, required=[]),
        handler=_git_diff,
    ),
    Tool(
        name="git_commit",
        description=(
            "Stage everything and commit with the given message. Commit once per "
            "coherent step so the history is reviewable. Requires human approval."
        ),
        input_schema=obj_schema(
            {
                "message": {
                    "type": "string",
                    "description": "Imperative subject line, optionally a body after a blank line.",
                }
            }
        ),
        handler=_git_commit,
        mutating=True,
    ),
]
