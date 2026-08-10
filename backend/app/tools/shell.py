"""Command execution.

Commands are untrusted model output, so this module never hands a string to a
shell. It tokenises with shlex, checks the executable against an allowlist,
rejects shell metacharacters outright, resolves the binary via PATH, and runs
it with a timeout inside the workspace. A denylist would not be sufficient.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext, ToolResult, obj_schema

# Interpreters resolved from PATH would be the machine's *global* Python, so an
# agent running `pip install` would mutate the user's system installation and
# `python -m pytest` would miss the project's dependencies. Both were observed
# on the first live run. These names are resolved against a project environment
# instead — see resolve_interpreter_dir.
ENVIRONMENT_SCOPED = frozenset({"python", "python3", "py", "pip", "pip3", "pytest"})
BIN_DIR = "Scripts" if os.name == "nt" else "bin"

COMMAND_TIMEOUT_SECONDS = 180
MAX_OUTPUT_CHARS = 12_000

# Executables the developer may invoke. Anything else is refused.
ALLOWED_EXECUTABLES = frozenset(
    {
        "python", "python3", "py", "pip", "pip3", "pytest",
        "node", "npm", "npx", "yarn", "pnpm",
        "ruff", "black", "mypy", "flake8", "eslint", "prettier", "tsc",
        "make", "cat", "ls", "echo",
    }
)

# Sub-commands that would take the run outside "edit this repo".
DENIED_ARGUMENTS = frozenset({"publish", "deploy", "--registry", "login", "token"})

# Characters that only mean anything to a shell. Their presence means the model
# is trying to chain commands, so we refuse the whole thing.
SHELL_METACHARACTERS = ("&&", "||", "|", ";", ">", "<", "`", "$(", "\n")

TEST_COMMANDS: dict[str, list[str]] = {
    "pytest": ["python", "-m", "pytest", "-q"],
    "npm": ["npm", "test", "--silent"],
}


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    head = text[: MAX_OUTPUT_CHARS // 2]
    tail = text[-MAX_OUTPUT_CHARS // 2 :]
    return f"{head}\n... [{len(text) - MAX_OUTPUT_CHARS} chars truncated] ...\n{tail}"


def resolve_interpreter_dir(workspace_root: Path | None) -> Path:
    """Where `python`/`pip`/`pytest` should come from.

    A virtual environment inside the workspace wins, because that is the
    project's own environment. Otherwise the interpreter running this server is
    used: it already has the dependencies, and it keeps an agent's `pip install`
    out of the machine's global site-packages.
    """
    if workspace_root is not None:
        for name in (".venv", "venv", "env"):
            candidate = Path(workspace_root) / name / BIN_DIR
            if candidate.is_dir():
                return candidate
    return Path(sys.executable).parent


def _tokenize(command: str) -> tuple[list[str], str | None]:
    if not command or not command.strip():
        return [], "empty command"
    for meta in SHELL_METACHARACTERS:
        if meta in command:
            return [], (
                f"refused: {meta!r} chains or redirects commands. Run one command "
                "per call."
            )
    try:
        argv = shlex.split(command, posix=False)
    except ValueError as exc:
        return [], f"could not parse command: {exc}"
    return (argv, None) if argv else ([], "empty command")


def _executable_name(token: str) -> str:
    """Strip quoting, directories and the Windows suffix from argv[0]."""
    name = token.strip('"').replace("\\", "/").rsplit("/", 1)[-1]
    return name.removesuffix(".exe").removesuffix(".cmd")


def _locate(executable: str, interpreter_dir: Path | None) -> str | None:
    """Prefer the project environment for interpreters, else fall back to PATH."""
    if interpreter_dir is not None and executable in ENVIRONMENT_SCOPED:
        suffixes = (".exe", ".cmd", "") if os.name == "nt" else ("",)
        for suffix in suffixes:
            candidate = Path(interpreter_dir) / f"{executable}{suffix}"
            if candidate.is_file():
                return str(candidate)
    return shutil.which(executable)


def vet(command: str, interpreter_dir: Path | None = None) -> tuple[list[str], str | None]:
    """Return (argv, error). `error` is non-None when the command is refused."""
    argv, error = _tokenize(command)
    if error:
        return [], error

    executable = _executable_name(argv[0])
    if executable not in ALLOWED_EXECUTABLES:
        return [], (
            f"refused: {executable!r} is not on the allowlist. Allowed: "
            f"{', '.join(sorted(ALLOWED_EXECUTABLES))}."
        )

    denied = DENIED_ARGUMENTS.intersection(a.lower() for a in argv[1:])
    if denied:
        return [], f"refused: argument(s) {sorted(denied)} are not permitted."

    resolved = _locate(executable, interpreter_dir)
    if resolved is None:
        return [], f"{executable!r} is not installed or not on PATH."
    return [resolved, *argv[1:]], None


async def _spawn(ctx: ToolContext, argv: list[str], timeout: int) -> ToolResult:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(ctx.sandbox.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        return ToolResult.error(f"failed to start command: {exc}")

    try:
        async with asyncio.timeout(timeout):
            stdout, _ = await process.communicate()
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return ToolResult.error(f"command timed out after {timeout}s")

    output = _truncate(stdout.decode("utf-8", errors="replace"))
    code = process.returncode or 0
    body = f"exit code: {code}\n\n{output or '(no output)'}"
    return ToolResult(
        content=body,
        is_error=code != 0,
        metadata={"exit_code": code, "argv": argv},
    )


async def _run_command(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    command = args["command"]
    argv, error = vet(command, resolve_interpreter_dir(ctx.sandbox.root))
    if error:
        return ToolResult.error(error)

    approved, reason = await ctx.confirm(
        "run_command", f"Run: {command}", {"command": command}
    )
    if not approved:
        return ToolResult.error(f"Human declined: {reason}")
    return await _spawn(ctx, argv, COMMAND_TIMEOUT_SECONDS)


async def run_suite(
    ctx: ToolContext, runner: str = "pytest", path: str | None = None
) -> ToolResult:
    """Run a project's test suite. Shared by the QA tool and the run baseline."""
    argv_template = TEST_COMMANDS.get(runner.lower())
    if argv_template is None:
        return ToolResult.error(
            f"unknown runner {runner!r}; expected one of {sorted(TEST_COMMANDS)}"
        )
    command = " ".join(argv_template + ([path] if path else []))
    argv, error = vet(command, resolve_interpreter_dir(ctx.sandbox.root))
    if error:
        return ToolResult.error(error)
    return await _spawn(ctx, argv, COMMAND_TIMEOUT_SECONDS)


async def _run_tests(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Running the suite is read-only in effect, so it skips the approval gate."""
    return await run_suite(ctx, args.get("runner") or "pytest", args.get("path"))


SHELL_TOOLS: list[Tool] = [
    Tool(
        name="run_command",
        description=(
            "Run a single command in the workspace, e.g. 'pip install pyjwt' or "
            "'ruff check .'. One command per call — pipes, redirects and '&&' are "
            "refused. Only allowlisted executables run. Requires human approval."
        ),
        input_schema=obj_schema(
            {
                "command": {
                    "type": "string",
                    "description": "The command line, e.g. 'python -m pytest -q'.",
                }
            }
        ),
        handler=_run_command,
        mutating=True,
        # The one tool whose effects escape the run's branch: an installed
        # package or a network call survives `git reset`.
        reversible=False,
    ),
    Tool(
        name="run_tests",
        description=(
            "Run the project's test suite and return the raw output. Use this to "
            "verify a change rather than asserting it works. Needs no approval."
        ),
        input_schema=obj_schema(
            {
                "runner": {
                    "type": "string",
                    "description": "'pytest' (default) or 'npm'.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional test file or directory to narrow the run.",
                },
            },
            required=[],
        ),
        handler=_run_tests,
    ),
]
