"""Workspace provisioning.

The crew never works in `demo-repo/` directly. That directory is the pristine
template; each provisioning copies it into a scratch workspace under `data/`.
Three things fall out of that: the committed demo repo never accumulates an
`agent/*` branch history or a nested `.git`, every benchmark starts from an
identical state, and resetting after a bad run is a directory delete rather
than a git surgery.

Pointing WORKSPACE_ROOT at a real project you own disables this — an existing,
non-empty directory is used as-is and never overwritten.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("crew.workspace")

IGNORED = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".pytest_cache", "node_modules", ".venv", ".env"
)


def is_empty(path: Path) -> bool:
    return not path.exists() or not any(path.iterdir())


def _clear_readonly(func: Callable[[str], Any], path: str, _exc: Any) -> None:
    """rmtree error handler that clears the read-only bit and retries.

    Git marks everything under `.git/objects` read-only, and on Windows that
    makes `os.unlink` raise PermissionError — so a workspace becomes
    undeletable the moment a run creates a repository in it.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: Path, attempts: int = 5) -> None:
    """Delete a tree, working around two Windows behaviours.

    Read-only files (git objects) are handled by `_clear_readonly`. Handles that
    a just-exited subprocess has not released yet raise WinError 32, so the
    delete is retried briefly before giving up.
    """
    for attempt in range(attempts):
        try:
            # `onerror` is deprecated from 3.12 in favour of `onexc`, but it is
            # the only spelling available on 3.11, which this project targets.
            shutil.rmtree(path, onerror=_clear_readonly)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def clear_directory(root: Path, attempts: int = 5) -> None:
    """Empty a directory without deleting it.

    Windows refuses to remove a directory that is any live process's working
    directory, and the crew has just been running pytest and git in this one.
    Removing the *children* and reusing the directory sidesteps that entirely.
    """
    for attempt in range(attempts):
        try:
            for child in root.iterdir():
                if child.is_dir() and not child.is_symlink():
                    remove_tree(child)
                else:
                    child.chmod(stat.S_IWRITE)
                    child.unlink()
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def provision(root: Path, template: Path | None, *, force: bool = False) -> bool:
    """Ensure `root` holds a working copy. Returns True when it was (re)created.

    Without `force`, an existing non-empty workspace is left alone: a run in
    progress, or a user's own repository, must never be clobbered on startup.
    """
    root = Path(root)
    if template is None:
        root.mkdir(parents=True, exist_ok=True)
        return False

    template = Path(template)
    if not template.exists():
        log.warning("workspace template %s does not exist; leaving %s as-is", template, root)
        root.mkdir(parents=True, exist_ok=True)
        return False

    if not force and not is_empty(root):
        return False

    root.mkdir(parents=True, exist_ok=True)
    clear_directory(root)
    shutil.copytree(template, root, ignore=IGNORED, dirs_exist_ok=True)
    log.info("provisioned workspace %s from template %s", root, template)
    return True
