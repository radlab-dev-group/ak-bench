"""Harness: the test file must pass on the correct code and fail on the
defective code. The defective variant is a one-line mutation of the
fixture, swapped in for a second run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import garden

TEST_REL = Path('tests/test_water_agent.py')
DEFECTIVE = {'src/garden/water.py': '"""When a plant needs water.\n\nThe rules:\n\n1. A plant is due on ``last_watered_day + interval_days``. The due day\n   itself counts: on that day the plant needs water.\n2. Rain on a day postpones watering for that day only. A plant that is due\n   and it rains needs no water that day, but it needs water on the next\n   day that does not rain.\n3. Before the due day a plant never needs water, rain or not.\n"""\n\nfrom __future__ import annotations\n\nfrom collections.abc import Collection\n\nfrom garden.model import Plant\n\n\ndef due_day(plant: Plant) -> int:\n    """The day the plant is next due for water."""\n    return plant.last_watered_day + plant.interval_days\n\n\ndef needs_water(plant: Plant, day: int, *, rain_days: Collection[int] = ()) -> bool:\n    """True when the plant needs water on ``day``, under the rules above."""\n    return day > due_day(plant) and day not in rain_days\n\n\ndef days_until_due(plant: Plant, day: int) -> int:\n    """Whole days from ``day`` until the due day; zero once due or overdue."""\n    return max(0, due_day(plant) - day)\n'}

def _repo_root() -> Path:
    return Path(garden.__file__).resolve().parents[2]


def _run(defective: bool) -> subprocess.CompletedProcess:
    root = _repo_root()
    agent_file = root / TEST_REL
    assert agent_file.is_file(), f"missing {TEST_REL}: write your tests there"
    tmp = Path(tempfile.mkdtemp(prefix="agent-tests-"))
    work = tmp / "repo"
    shutil.copytree(
        root,
        work,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )

    if defective:
        for rel, content in DEFECTIVE.items():
            (work / rel).write_text(content)
    env = {**os.environ, "PYTHONPATH": str(work / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(work / TEST_REL)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_tests_pass_on_the_correct_code():
    result = _run(defective=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_tests_fail_on_the_defective_code():
    result = _run(defective=True)
    assert result.returncode != 0, "the tests pass on defective code: they do not pin the behaviour"
