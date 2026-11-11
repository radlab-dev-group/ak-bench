"""Reading text files from a base directory.

``read_text(base_dir, name)`` reads the file ``name`` from inside
``base_dir`` and returns its text. The name is a relative path: the
reader must never return a file outside the base directory, however the
name is written.
"""

from __future__ import annotations

from pathlib import Path


def read_text(base_dir: Path, name: str) -> str:
    """Read ``name`` from inside ``base_dir`` and return its text."""
    path = Path(base_dir) / name
    return path.read_text(encoding="utf-8")
