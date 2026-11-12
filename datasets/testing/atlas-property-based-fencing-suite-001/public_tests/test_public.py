"""What the harness will check about your file, checked from your side.

Run these from the repository root once you have written
tests/test_fencing_stateful.py. They cover the shape of the deliverable; the
mutant detection power is what the hidden harness adds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_TEST = Path("tests/test_fencing_stateful.py")


def _root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "atlas").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared atlas workspace")


def _run(root: Path, *, patch: tuple[Path, str, str] | None = None) -> subprocess.CompletedProcess:
    work = Path(tempfile.mkdtemp(prefix="drift-")) / "repo"
    shutil.copytree(root, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    if patch is not None:
        relative, old, new = patch
        target = work / relative
        text = target.read_text(encoding="utf-8")
        assert old in text, f"the drift anchor disappeared from {relative}"
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
    environment = {
        **os.environ,
        "PYTHONPATH": str(work / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        return subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                str(work / AGENT_TEST),
            ],
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
            timeout=600,
        )
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)


def test_the_suite_file_exists():
    assert (_root() / AGENT_TEST).is_file(), f"write your suite in {AGENT_TEST}"


def test_the_suite_passes_on_the_store_as_it_is():
    root = _root()
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_suite_notices_a_lease_book_that_moves_sideways():
    root = _root()
    result = _run(
        root,
        patch=(
            Path("src/atlas/fencing.py"),
            "if previous is not None and generation <= previous.generation:",
            "if previous is not None and generation < previous.generation:",
        ),
    )
    assert result.returncode != 0, (
        "the suite is green with a lease book that lets a holder take a generation "
        "it does not have; it is not modelling the forward-only rule"
    )
