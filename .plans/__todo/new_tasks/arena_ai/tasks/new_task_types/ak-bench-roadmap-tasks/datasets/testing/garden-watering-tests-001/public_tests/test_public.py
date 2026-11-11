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

SAMPLE = '"""Tests for garden.water: due days, rain, countdown."""\n\nfrom __future__ import annotations\n\nfrom garden.model import Plant\nfrom garden.water import days_until_due, due_day, needs_water\n\nFERN = Plant("fern", "Fern", last_watered_day=10, interval_days=3)  # due on day 13\n\n\ndef test_due_day_is_last_watered_plus_interval():\n    assert due_day(FERN) == 13\n\n\ndef test_the_due_day_itself_needs_water():\n    assert needs_water(FERN, 13)\n    assert needs_water(FERN, 14)\n    assert not needs_water(FERN, 12)\n\n\ndef test_rain_postpones_watering_for_that_day_only():\n    assert not needs_water(FERN, 13, rain_days={13})\n    assert needs_water(FERN, 14, rain_days={13})\n    assert not needs_water(FERN, 12, rain_days={12})\n\n\ndef test_days_until_due_counts_down_to_zero():\n    assert days_until_due(FERN, 10) == 3\n    assert days_until_due(FERN, 12) == 1\n    assert days_until_due(FERN, 13) == 0\n    assert days_until_due(FERN, 20) == 0\n'

def _repo_root() -> Path:
    return Path(garden.__file__).resolve().parents[2]


def _run(defective: bool) -> subprocess.CompletedProcess:
    root = _repo_root()
    pass  # the sample is written into the copy below
    tmp = Path(tempfile.mkdtemp(prefix="agent-tests-"))
    work = tmp / "repo"
    shutil.copytree(
        root,
        work,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    (work / TEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (work / TEST_REL).write_text(SAMPLE)
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
