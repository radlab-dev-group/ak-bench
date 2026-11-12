"""Harness for the atlas-drift suite.

The agent writes tests/test_fencing_stateful.py. It has to pass against the
repository as it stands, and fail against each of the four single-comparison
mutants below. The mutants are applied here, to a throwaway copy, and are never
shipped inside the repository.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import atlas

AGENT_TEST = Path("tests/test_fencing_stateful.py")
RUN_TIMEOUT_SECONDS = 300

#: id -> (module, the line the mutant changes, what it changes it to)
MUTANTS: dict[str, tuple[str, str, str]] = {
    "drift-001": (
        "src/atlas/fencing.py",
        "if previous is not None and generation <= previous.generation:",
        "if previous is not None and generation < previous.generation:",
    ),
    "drift-002": (
        "src/atlas/fencing.py",
        "            if offered_generation != held:",
        "            if offered_generation < held:",
    ),
    "drift-003": (
        "src/atlas/repair.py",
        "if tie_break_key(record.vector) > tie_break_key(best.vector):",
        "if tie_break_key(record.vector) < tie_break_key(best.vector):",
    ),
    "drift-004": (
        "src/atlas/storage.py",
        "            if observed != expected_generation:",
        "            if observed > expected_generation:",
    ),
}


def _repo_root() -> Path:
    return Path(atlas.__file__).resolve().parents[2]


def _run(mutant: str | None) -> subprocess.CompletedProcess:
    root = _repo_root()
    agent_file = root / AGENT_TEST
    assert agent_file.is_file(), f"missing {AGENT_TEST}: write your suite there"
    scratch = Path(tempfile.mkdtemp(prefix="drift-harness-"))
    work = scratch / "repo"
    try:
        shutil.copytree(
            root, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache")
        )
        if mutant is not None:
            relative, old, new = MUTANTS[mutant]
            target = work / relative
            text = target.read_text(encoding="utf-8")
            assert old in text, f"the drift anchor is missing from {relative}"
            target.write_text(text.replace(old, new, 1), encoding="utf-8")
        environment = {
            **os.environ,
            "PYTHONPATH": str(work / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                str(work / AGENT_TEST),
            ],
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_the_suite_passes_on_the_store_as_it_is():
    started = time.time()
    result = _run(None)
    assert result.returncode == 0, (
        "the suite must be green on the repository as it stands "
        f"(no skips, no xfail, no dependence on a defect):\n{result.stdout}\n{result.stderr}"
    )
    assert "no tests ran" not in result.stdout, "the suite collected no tests"
    assert time.time() - started < RUN_TIMEOUT_SECONDS


@pytest.mark.parametrize("mutant", sorted(MUTANTS))
def test_the_suite_detects_the_drift_family(mutant: str):
    result = _run(mutant)
    assert result.returncode != 0, (
        f"{mutant} was not detected: the suite is green with "
        f"{MUTANTS[mutant][0]} mutated ({MUTANTS[mutant][1]!r} -> {MUTANTS[mutant][2]!r})"
    )
