"""The split is real, and the edges between the parts go one way.

A package with one big module and four empty ones passes the behavioural tests
and teaches nobody anything, so this checks the shape as well: the engine is
several modules, none of them the old size, and no two of them import each
other.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

def _workspace_root() -> Path:
    """The root of the checkout under test.

    Hidden tests are copied into the workspace at evaluation time and one
    directory deeper when the dataset validator verifies a mutation, so the
    root is found by walking up to the project marker rather than counting
    directories.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise AssertionError("the checkout under test was not found")


ROOT = _workspace_root()
ENGINE = ROOT / "src" / "depweaver" / "solver"


def _modules() -> list[Path]:
    if not ENGINE.is_dir():
        return []
    return sorted(path for path in ENGINE.glob("*.py") if path.name != "__init__.py")


def test_the_engine_is_a_package_of_several_modules():
    assert ENGINE.is_dir(), "src/depweaver/solver/ is the package this task creates"
    modules = _modules()
    assert len(modules) >= 4, (
        f"the engine is {len(modules)} module(s); the trail, the watchers, the analysis and the loop are at least four"
    )


def test_no_module_is_the_old_monolith():
    for path in _modules():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= 220, f"{path.name} is {lines} lines; the split left it a monolith"


def test_the_package_reexports_the_public_names():
    from depweaver import solver

    for name in ("Activities", "Solver", "Trail", "Watchers", "encode", "resolve"):
        assert hasattr(solver, name), f"depweaver.solver no longer exports {name}"


def test_the_modules_do_not_import_each_other_in_a_cycle():
    edges: dict[str, set[str]] = {}
    for path in _modules():
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                names.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("depweaver.solver."):
                        names.add(alias.name.split(".")[2])
        edges[path.stem] = {name for name in names if name != path.stem}

    for name, targets in sorted(edges.items()):
        for target in sorted(targets):
            assert name not in edges.get(target, set()), (
                f"{name} imports {target} and {target} imports {name}: the split has a cycle in it"
            )


def test_the_repository_suite_still_passes():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
