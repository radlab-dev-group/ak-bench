"""The twelve reference traces, byte for byte, after the split.

The shell is allowed to be new; the behaviour is not. Every schedule in the
corpus runs through the refactored node and has to land on the digest the seed
recorded before the split.
"""

from __future__ import annotations

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
SCHEDULES = sorted(path.stem for path in (ROOT / "schedules").glob("*.json"))


def _reference(name: str) -> dict:
    fields = {}
    for line in (ROOT / "traces" / f"{name}.digest").read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition(" ")
        fields[key] = value.strip()
    return fields


@pytest.mark.parametrize("name", SCHEDULES)
def test_the_trace_digest_matches_the_reference(name: str):
    from tidewater.cluster import Cluster
    from tidewater.schedule import load_schedule

    result = Cluster(load_schedule(ROOT / "schedules" / f"{name}.json")).run()
    assert result.ok, f"{name}: {result.violation}"
    assert result.digest == _reference(name)["trace_digest"], f"{name}: the trace moved"


def test_a_stepped_node_ends_where_a_ticked_one_does():
    """The effects path and the legacy path are the same node, not two."""
    from tidewater.effects import Tick
    from tidewater.membership import Configuration
    from tidewater.node import Node, NodeOptions
    from tidewater.clock import NodeClock
    from tidewater.rng import SeedTree
    from tidewater.runtime.actor_runner import ActorRunner
    from tidewater.storage import Storage
    from tidewater.trace import Trace

    voters = ("n1", "n2", "n3")

    def build(trace: Trace) -> Node:
        return Node(
            node_id="n1",
            config=Configuration.of(voters),
            storage=Storage("n1", voters),
            rng=SeedTree(11).stream("n1", "election"),
            clock=NodeClock(),
            trace=trace,
            options=NodeOptions(election_timeout=20, heartbeat_interval=5),
        )

    legacy_trace, stepped_trace = Trace(), Trace()
    legacy, stepped = build(legacy_trace), build(stepped_trace)
    runner = ActorRunner(stepped_trace)

    for tick in range(120):
        legacy.tick(tick)
        _state, effects = stepped.step(Tick(tick))
        runner.apply(stepped, effects)
        legacy.drain_outbox()
        stepped.drain_outbox()

    assert [(e.tick, e.node, e.kind, e.fields) for e in stepped_trace.events] == [
        (e.tick, e.node, e.kind, e.fields) for e in legacy_trace.events
    ], "stepping a node does not produce the trace that ticking it produces"
    assert (stepped.role, stepped.current_term, stepped.log.last_index) == (
        legacy.role,
        legacy.current_term,
        legacy.log.last_index,
    )


def test_the_repository_suite_still_passes():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
