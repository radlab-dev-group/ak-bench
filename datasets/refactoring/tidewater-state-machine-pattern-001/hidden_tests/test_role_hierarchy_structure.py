"""The roles are classes, they share a base, and Node no longer asks which one it is."""

from __future__ import annotations

import inspect
import re
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
NODE = ROOT / "src" / "tidewater" / "node.py"
ROLES = ROOT / "src" / "tidewater" / "roles"

ROLE_NAMES = ("follower", "pre_candidate", "candidate", "leader")


def _package():
    import tidewater.roles as package

    return package


def test_the_package_is_there():
    assert ROLES.is_dir(), "src/tidewater/roles/ is the decomposition this task is about"
    assert any(ROLES.glob("*.py")), "src/tidewater/roles/ has no modules"


def test_the_four_roles_are_classes_with_the_two_operations():
    package = _package()
    found = {
        name: obj
        for name, obj in vars(package).items()
        if inspect.isclass(obj) and name.endswith("Role") and name != "BaseRole"
    }
    assert len(found) >= 4, f"expected a class per role, found {sorted(found)}"
    for name, role in sorted(found.items()):
        for operation in ("on_tick", "on_receive"):
            assert callable(getattr(role, operation, None)), f"{name} implements no {operation}()"


def test_the_roles_share_one_base_role():
    package = _package()
    roles = [
        obj for obj in vars(package).values()
        if inspect.isclass(obj) and obj.__name__.endswith("Role") and obj.__name__ != "BaseRole"
    ]
    bases = {base.__name__ for role in roles for base in role.__mro__[1:-2]}
    shared = set(bases)
    for role in roles[1:]:
        shared &= {base.__name__ for base in role.__mro__[1:-2]}
    assert shared, "the role classes do not share a base class, so the common rules are copied again"


def test_the_package_maps_role_names_to_classes():
    package = _package()
    mapping = getattr(package, "ROLES", None)
    assert isinstance(mapping, dict), "tidewater.roles exports ROLES: role name -> class"
    assert sorted(mapping) == sorted(ROLE_NAMES), (
        f"ROLES is keyed by the names the trace uses: expected {sorted(ROLE_NAMES)}, got {sorted(mapping)}"
    )
    for name, role in mapping.items():
        assert inspect.isclass(role), f"ROLES[{name!r}] is not a class"


@pytest.mark.parametrize("name", ROLE_NAMES)
def test_the_role_names_the_trace_uses_are_unchanged(name: str):
    from tidewater import node as node_module

    constants = {node_module.FOLLOWER, node_module.PRE_CANDIDATE, node_module.CANDIDATE, node_module.LEADER}
    assert name in constants, f"tidewater.node no longer exports the role name {name!r}"


def test_node_no_longer_branches_on_its_role():
    text = NODE.read_text(encoding="utf-8")
    branches = re.findall(r"self\.role\s*[!=]=+", text)
    assert len(branches) <= 1, (
        f"src/tidewater/node.py still asks which role it is {len(branches)} times; the branches belong to the roles"
    )


def test_node_is_no_longer_the_whole_protocol():
    lines = len(NODE.read_text(encoding="utf-8").splitlines())
    assert lines <= 300, (
        f"src/tidewater/node.py is {lines} lines; the delegation was supposed to leave it under 300"
    )
