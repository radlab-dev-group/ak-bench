"""The review, checked against the seeded issues in the PR.

Both flaws are in one file — the cache lookup and the collector's signature —
and each finding has to be cited where it is.
"""

from __future__ import annotations

import re
from pathlib import Path

import racekit

ROOT = Path(racekit.__file__).resolve().parents[2]
REVIEW = ROOT / "REVIEW.md"

#: A review shorter than this has not looked at the code.
MIN_LENGTH = 200

#: One entry per seeded issue, as ``(words, file, needles)``: the words a
#: reviewer has to use, the file the flaw is in, and the code the citation has
#: to land on. ``needles=None`` asks for a citation anywhere in the file, which
#: is enough for an issue that is an absence — a missing test, docs that were
#: never updated — where the point of the finding is the file to change.
ISSUES = [
    (
        ["race", "thread", "lock", "atomic", "check-then-act"],
        "src/racekit/cache.py",
        ["if key not in _cache", "_cache[key] = factory()"],
    ),
    (
        ["mutable default", "default argument", "shared"],
        "src/racekit/cache.py",
        ["def collect(items: list = [])"],
    ),
]

#: A review that cites every line of the repository is a spray, not a review.
#: The cap sits far above what the seeded issues need; it only catches spray.
MAX_CITATIONS = 4 * len(ISSUES) + 2

#: ``path:line``, the way a reviewer points at code: ``src/pkg/mod.py:12``.
_CITATION = re.compile(r"(?P<path>[A-Za-z0-9_./\-]+\.(?:py|md)):(?P<line>\d+)")


def _review_text() -> str:
    assert REVIEW.is_file(), "REVIEW.md is missing at the repository root"
    text = REVIEW.read_text(encoding="utf-8")
    assert len(text) >= MIN_LENGTH, "the review is too short to cover the PR"
    return text


def _citations(text: str) -> list[tuple[str, int]]:
    return [
        (match.group("path"), int(match.group("line")))
        for match in _CITATION.finditer(text)
    ]


def _resolve(cited: str) -> Path | None:
    """The repository file a citation names, or ``None`` when it names none."""
    direct = ROOT / cited
    if direct.is_file():
        return direct
    parts = Path(cited).parts
    matches = [
        path
        for path in sorted(ROOT.rglob("*"))
        if path.is_file() and path.parts[-len(parts):] == parts and ".git" not in path.parts
    ]
    return matches[0] if len(matches) == 1 else None


def _blocks(lines: list[str]) -> dict[int, tuple[int, int]]:
    """The block that holds each 1-based line: a top-level def or class.

    A citation is matched against the block, not the exact line, so a reviewer
    who points at the ``def`` line rather than the statement inside it is not
    penalised, and one who points at the wrong function still is. Lines outside
    any def or class — a module-level constant, a rename — belong to no block:
    there the citation has to name the line itself.
    """
    starts = [
        index + 1
        for index, text in enumerate(lines)
        if text.startswith(("def ", "class "))
    ]
    blocks: dict[int, tuple[int, int]] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] - 1 if position + 1 < len(starts) else len(lines)
        for line in range(start, end + 1):
            blocks[line] = (start, end)
    return blocks


def _check_issue(text: str, number: int) -> None:
    words, target, needles = ISSUES[number - 1]
    lowered = text.lower()
    assert any(word in lowered for word in words), (
        f"issue {number} is not mentioned in REVIEW.md"
    )

    citations = _citations(text)
    assert len(set(citations)) <= MAX_CITATIONS, (
        f"REVIEW.md cites {len(set(citations))} locations: a review, not a dump of the tree"
    )

    cited_lines = [
        line
        for path, line in citations
        if (resolved := _resolve(path)) is not None and resolved == ROOT / target
    ]
    assert cited_lines, f"issue {number}: the review never cites {target}"

    if needles is None:
        return

    lines = (ROOT / target).read_text(encoding="utf-8").splitlines()
    blocks = _blocks(lines)
    anchors = [
        index + 1 for index, text in enumerate(lines) if any(n in text for n in needles)
    ]
    assert anchors, f"the fixture lost the code issue {number} is about: {needles}"
    expected = {blocks.get(anchor) for anchor in anchors}
    for line in cited_lines:
        if blocks.get(line) in expected or (blocks.get(line) is None and line in anchors):
            return
    raise AssertionError(
        f"issue {number}: REVIEW.md cites {target} but not the code that is wrong in it"
    )


def test_finds_issue_1():
    _check_issue(_review_text(), 1)


def test_finds_issue_2():
    _check_issue(_review_text(), 2)

