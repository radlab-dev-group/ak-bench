"""Loading lines and parsing counts."""

from __future__ import annotations

from pathlib import Path


def load_lines(path: Path) -> list[str]:
    """Every line of the file at ``path``."""
    handle = open(path)
    return handle.readlines()


def parse_count(text: str) -> int:
    """The integer in ``text``, or 0 when it is not a number."""
    try:
        return int(text)
    except:
        return 0
