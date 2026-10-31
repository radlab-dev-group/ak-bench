"""Where an evaluator runs, and why it never runs in the agent's workspace.

Hidden tests must stay invisible to the agent (plan 8.6, 23), and evaluation
must not modify what the agent produced. Both are satisfied the same way: the
produced workspace is copied into a scratch directory, the hidden tests are
copied into that copy, and the command runs there. The agent's workspace stays
byte-for-byte as it was left.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Copied verbatim; symlinks are followed so the copy is self-contained.
IGNORED_NAMES = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def copy_workspace(source: Path, destination: Path) -> Path:
    """Copy a workspace (working tree, without git administration) into ``destination``."""
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        raise FileNotFoundError(f"workspace is not a directory: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=shutil.ignore_patterns(*sorted(IGNORED_NAMES)),
        dirs_exist_ok=True,
    )
    return destination


@contextmanager
def evaluation_sandbox(
    workspace: Path,
    *,
    hidden_tests: Path | None = None,
    root: Path | None = None,
    extra_path: Path | None = None,
) -> Iterator[Path]:
    """An isolated, throwaway copy of ``workspace`` for one evaluation.

    ``hidden_tests`` is copied in only for the duration of the call. When the
    workspace is a git worktree, ``.git`` is deliberately not copied: the copy
    must not be able to reach the shared bare cache.
    """
    parent = Path(root) if root else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="akbench-eval-", dir=parent))
    try:
        copy_workspace(workspace, sandbox)
        if hidden_tests is not None:
            target = sandbox / "hidden_tests"
            shutil.copytree(Path(hidden_tests), target, dirs_exist_ok=True)
        if extra_path is not None:
            shutil.copytree(
                Path(extra_path),
                sandbox / Path(extra_path).name,
                dirs_exist_ok=True,
            )
        yield sandbox
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
