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

import timetable

TEST_REL = Path('tests/test_overlap_agent.py')
DEFECTIVE = {'src/timetable/overlap.py': '"""Whether lessons overlap. Intervals are half-open: ``[start, end)``.\n\nTwo intervals overlap when each starts before the other ends. An interval\nthat ends exactly when the other starts does not overlap it, so\nback-to-back lessons are free to follow each other.\n"""\n\nfrom __future__ import annotations\n\nfrom collections.abc import Iterable\n\nfrom timetable.model import Lesson\n\n\ndef overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:\n    """True when ``[a_start, a_end)`` and ``[b_start, b_end)`` share a minute."""\n    return a_start <= b_end and b_start <= a_end\n\n\ndef conflicts(lessons: Iterable[Lesson]) -> list[tuple[str, str]]:\n    """Every pair of lesson ids that overlap, in a deterministic order.\n\n    Each pair is ``(smaller_id, larger_id)`` and the list is sorted, so the\n    result depends only on the lessons, never on the order they were given.\n    """\n    lessons = list(lessons)\n    pairs: list[tuple[str, str]] = []\n    for index, first in enumerate(lessons):\n        for second in lessons[index + 1 :]:\n            if overlaps(first.start, first.end, second.start, second.end):\n                pairs.append(tuple(sorted((first.lesson_id, second.lesson_id))))\n    return sorted(pairs)\n\n\ndef is_free(lessons: Iterable[Lesson], start: int, end: int) -> bool:\n    """True when no lesson overlaps ``[start, end)``."""\n    if end <= start:\n        raise ValueError(f"end must be after start, got [{start}, {end})")\n    return not any(\n        overlaps(start, end, lesson.start, lesson.end) for lesson in lessons\n    )\n'}

def _repo_root() -> Path:
    return Path(timetable.__file__).resolve().parents[2]


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
