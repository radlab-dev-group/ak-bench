"""A taste of the acceptance criteria, for running locally before submission.

The hidden tests say the same thing more strictly; these only show the shape.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared workspace")


ROOT = _source_root()
sys.path.insert(0, str(ROOT / "src"))

import atlas  # noqa: E402


def test_the_engine_package_exists():
    import atlas.engines

    assert hasattr(atlas.engines, "StorageEngine") or hasattr(
        atlas.engines.base, "StorageEngine"
    ), "atlas.engines must define the StorageEngine protocol"


def test_the_memory_engine_stores_records():
    from atlas.engines import MemoryStorageEngine
    from atlas.values import Record

    engine = MemoryStorageEngine()
    record = Record.put("k", {"n": 1})
    assert engine.put(record) is True
    assert engine.get("k") == record
    assert engine.get("missing") is None
