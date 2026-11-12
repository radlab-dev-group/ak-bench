"""The engines sit in the durable half, and nothing above them leaks in.

`tools/check_arch.py` is the repository's own layer checker and the rules it
enforces are the ones `ADR-0014` states. The JSON next to this file extends
that map with the modules the task introduces, so the boundary is checked with
the tool rather than with a reimplementation of it.
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
SRC = ROOT / "src" / "atlas"

#: Modules above the durable half. An engine that imports one of these can no
#: longer be opened without standing up the protocol, which is the whole thing
#: the boundary exists to prevent.
ABOVE = {
    "fencing", "repair", "replication", "antientropy", "migration", "rebalance",
    "transaction", "cache", "store", "cli", "compat",
}


def _engine_files() -> list[Path]:
    directory = SRC / "engines"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*.py") if path.name != "__init__.py")


def _imports_of(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("atlas."):
                    names.add(alias.name.split(".")[1])
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module and node.module.startswith("atlas."):
            names.add(node.module.split(".")[1])
        elif isinstance(node, ast.ImportFrom) and node.level and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_engine_package_exists():
    assert (SRC / "engines").is_dir(), "src/atlas/engines/ is the boundary this task is about"
    assert _engine_files(), "src/atlas/engines/ holds no modules"


@pytest.mark.parametrize("name", ["base", "memory", "disk"])
def test_the_engine_modules_exist(name: str):
    assert (SRC / "engines" / f"{name}.py").is_file(), f"src/atlas/engines/{name}.py is missing"


def test_no_engine_imports_a_module_above_the_durable_half():
    offenders = []
    for path in _engine_files():
        for imported in sorted(_imports_of(path)):
            if imported in ABOVE:
                offenders.append(f"{path.name} imports atlas.{imported}")
    assert not offenders, "engine modules reach up the stack: " + "; ".join(offenders)


def test_the_repository_layer_checker_is_clean():
    rules = Path(__file__).resolve().parent / "arch_rules.json"
    completed = subprocess.run(
        [sys.executable, "tools/check_arch.py", "--rules", str(rules)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
