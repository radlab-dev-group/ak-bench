"""The shape of the split, for running locally."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared workspace")


ROOT = _source_root()


def test_reference_digests_still_match():
    completed = subprocess.run(
        [sys.executable, "tools/reference_traces.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_effects_module_exists():
    sys.path.insert(0, str(ROOT / "src"))
    from tidewater import effects  # noqa: F401


def test_a_node_step_returns_effects():
    sys.path.insert(0, str(ROOT / "src"))
    from tidewater.effects import Tick
    from tidewater.membership import Configuration
    from tidewater.node import Node, NodeOptions
    from tidewater.clock import NodeClock
    from tidewater.rng import SeedTree
    from tidewater.storage import Storage
    from tidewater.trace import Trace

    nodes = ("n1", "n2", "n3")
    node = Node(
        node_id="n1",
        config=Configuration.of(nodes),
        storage=Storage("n1", nodes),
        rng=SeedTree(1).stream("n1", "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(),
    )
    _state, effects = node.step(Tick(0))
    assert isinstance(effects, list)
