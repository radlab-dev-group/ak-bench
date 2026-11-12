"""The twelve reference traces, byte for byte.

A refactor that changes a digest has changed the protocol. The digests in
`traces/` are the behaviour, and this test is the one the task is really
about: everything else is style.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

def _workspace_root() -> Path:
    """The root of the checkout under test.

    Hidden tests are copied into the workspace at evaluation time and one
    directory deeper when the dataset validator verifies a mutation, so the
    root is found by walking up to the project marker rather than counting
    directories.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise AssertionError("the checkout under test was not found")


ROOT = _workspace_root()

SCHEDULES = sorted(path.stem for path in (ROOT / "schedules").glob("*.json"))


def _reference(name: str) -> dict:
    fields = {}
    for line in (ROOT / "traces" / f"{name}.digest").read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition(" ")
        fields[key] = value.strip()
    return fields


def test_the_corpus_is_the_twelve_schedules_the_task_promises():
    assert len(SCHEDULES) == 12, f"expected the twelve shipped schedules, found {SCHEDULES}"


@pytest.mark.parametrize("name", SCHEDULES)
def test_the_trace_digest_matches_the_reference(name: str, monitor):
    from tidewater.cluster import Cluster
    from tidewater.schedule import load_schedule

    result = Cluster(load_schedule(ROOT / "schedules" / f"{name}.json")).run()
    expected = _reference(name)
    monitor["events"] = result.events
    assert result.digest == expected["trace_digest"], (
        f"{name}: trace diverged at tick {monitor.get('first_divergence', '?')} "
        f"({monitor['events']} events produced)"
    )


@pytest.mark.parametrize("name", SCHEDULES)
def test_the_event_count_matches_the_reference(name: str):
    from tidewater.cluster import Cluster
    from tidewater.schedule import load_schedule

    result = Cluster(load_schedule(ROOT / "schedules" / f"{name}.json")).run()
    assert str(result.events) == _reference(name)["events"], f"{name}: the number of trace events changed"
    assert result.ok, f"{name}: the refactor introduced a {result.violation}"


def test_the_repository_suite_still_passes():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
