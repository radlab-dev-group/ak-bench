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

SAMPLE = '"""Tests for wordcount.text: counting and ranking."""\n\nfrom __future__ import annotations\n\nfrom wordcount import count_words, top_words\n\n\ndef test_count_words_counts_whitespace_separated_words():\n    assert count_words("") == 0\n    assert count_words("  \\n\\t ") == 0\n    assert count_words("one two three") == 3\n    assert count_words("  spaced   out  ") == 2\n\n\ndef test_top_words_returns_the_most_frequent_first():\n    assert top_words("a b a c a b", 2) == [("a", 3), ("b", 2)]\n    assert top_words("a b a c a b", 1) == [("a", 3)]\n\n\ndef test_top_words_is_case_insensitive():\n    assert top_words("Banana apple banana Apple", 2) == [("apple", 2), ("banana", 2)]\n\n\ndef test_top_words_breaks_ties_alphabetically():\n    assert top_words("pear fig pear fig", 2) == [("fig", 2), ("pear", 2)]\n\n\ndef test_top_words_respects_the_limit():\n    assert top_words("a a b", 0) == []\n    assert top_words("a a b", 10) == [("a", 2), ("b", 1)]\n'

def _repo_root() -> Path:
    return Path(wordcount.__file__).resolve().parents[2]


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
