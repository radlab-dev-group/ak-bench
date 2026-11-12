"""The node decides; it no longer reaches.

The claim being tested is narrow enough to check mechanically and wide enough
to matter: after the refactor, `src/tidewater/node.py` contains no side effect
of its own. It imports no transport, reads no clock, and does not touch the
outbox — it returns effects and something else acts.
"""

from __future__ import annotations

import ast
from pathlib import Path

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

FORBIDDEN_IMPORTS = {"network", "cluster", "socket", "random", "time", "threading", "subprocess"}
FORBIDDEN_CALLS = {"open", "print", "input", "sleep"}


def _tree() -> ast.Module:
    return ast.parse(NODE.read_text(encoding="utf-8"))


def test_the_node_imports_no_transport_and_no_wall_clock():
    offenders = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            for alias in node.names:
                offenders.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            offenders.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level and node.module:
            offenders.add(node.module.split(".")[0])
    used = offenders & FORBIDDEN_IMPORTS
    assert not used, f"src/tidewater/node.py imports {sorted(used)}; the shell owns those"


def test_the_node_calls_no_io_of_its_own():
    calls = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id in {"time", "os", "random", "socket"}:
                    calls.add(f"{node.func.value.id}.{node.func.attr}")
    hit = {name for name in calls if name.split(".")[0] in FORBIDDEN_CALLS or name in FORBIDDEN_CALLS}
    assert not hit, f"src/tidewater/node.py performs I/O directly: {sorted(hit)}"


def test_the_node_does_not_write_its_own_outbox():
    text = NODE.read_text(encoding="utf-8")
    appends = text.count("self.outbox.append") + text.count("self.outbox.extend")
    assert appends == 0, (
        f"src/tidewater/node.py still appends to the outbox {appends} times; "
        "a send is an effect now, and the shell performs it"
    )


def test_the_node_does_not_record_its_own_trace():
    text = NODE.read_text(encoding="utf-8")
    records = text.count("self.trace.record")
    assert records == 0, (
        f"src/tidewater/node.py still records {records} trace events itself; "
        "a trace record is an effect now"
    )
