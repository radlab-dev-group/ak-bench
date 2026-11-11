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

import wordcount

TEST_REL = Path('tests/test_text_agent.py')
DEFECTIVE = {'src/wordcount/text.py': 'from __future__ import annotations\n\n\ndef count_words(text: str) -> int:\n    """Count the whitespace-separated words in ``text``.\n\n    An empty or whitespace-only string contains zero words, no matter how many\n    blank lines it has.\n    """\n    return len(text.split())\n\n\ndef top_words(text: str, limit: int = 3) -> list[tuple[str, int]]:\n    """The most frequent words, case-insensitive, with their counts."""\n    counts: dict[str, int] = {}\n    for word in text.lower().split():\n        counts[word] = counts.get(word, 0) + 1\n    ranked = sorted(counts.items(), key=lambda item: (item[1], item[0]))\n    return ranked[: max(limit, 0)]\n'}

def _repo_root() -> Path:
    return Path(wordcount.__file__).resolve().parents[2]


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
