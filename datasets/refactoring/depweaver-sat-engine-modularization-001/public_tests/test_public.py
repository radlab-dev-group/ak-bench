"""The public import path and one golden lockfile, for running locally."""

from __future__ import annotations

import sys
from pathlib import Path

def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared workspace")


ROOT = _source_root()
sys.path.insert(0, str(ROOT / "src"))


def test_the_public_import_path_works():
    from depweaver.solver import Activities, Solver, Trail, Watchers, encode, resolve  # noqa: F401


def test_resolve_still_answers():
    from depweaver.solver import resolve

    packages = {"a": [("1.0.0", False), ("2.0.0", False)], "b": [("1.0.0", False)]}
    requirements = [("a", ["1.0.0", "2.0.0"]), ("b", ["1.0.0"])]
    assert resolve(packages, requirements) == {"a": "2.0.0", "b": "1.0.0"}
