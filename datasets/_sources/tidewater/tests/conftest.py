"""Shared fixtures and helpers for the Tidewater repository suite."""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tidewater.clock import NodeClock  # noqa: E402
from tidewater.cluster import Cluster  # noqa: E402
from tidewater.membership import Configuration  # noqa: E402
from tidewater.network import NetworkOptions  # noqa: E402
from tidewater.node import Node, NodeOptions  # noqa: E402
from tidewater.rng import SeedTree  # noqa: E402
from tidewater.schedule import Action, Schedule  # noqa: E402
from tidewater.storage import Storage  # noqa: E402
from tidewater.trace import Trace  # noqa: E402

FIVE = ("n1", "n2", "n3", "n4", "n5")
THREE = ("n1", "n2", "n3")


def make_schedule(name="t", nodes=FIVE, seed=11, ticks=1200, actions=(), **options):
    """A schedule with the default options unless overridden by keyword."""

    node_options = NodeOptions(**{k: v for k, v in options.items() if k in NodeOptions.__dataclass_fields__})
    network_options = NetworkOptions(**{k: v for k, v in options.items() if k in NetworkOptions.__dataclass_fields__})
    give_up_after = options.get("give_up_after", 0)
    return Schedule(
        name=name, nodes=tuple(nodes), seed=seed, ticks=ticks, actions=list(actions),
        node_options=node_options, network_options=network_options, give_up_after=give_up_after,
    )


def act(at, kind, **args):
    return Action(at=at, kind=kind, args=args)


def run_until(cluster: Cluster, predicate, max_ticks=2000):
    """Step the cluster until ``predicate(cluster)`` holds. Returns the tick
    at which it first held; fails the test if it never does."""

    start = cluster.now
    while cluster.now - start < max_ticks and not cluster.finished:
        if predicate(cluster):
            return cluster.now
        cluster.step()
    if predicate(cluster):
        return cluster.now
    pytest.fail(f"condition not reached within {max_ticks} ticks:\n{cluster.describe()}")


def wait_for_leader(cluster: Cluster, max_ticks=600) -> Node:
    run_until(cluster, lambda c: c.leader() is not None, max_ticks)
    return cluster.leader()


def make_node(node_id="n1", voters=THREE, seed=1, trace=None, sync_policy="always", **options) -> Node:
    """A standalone node with its own storage and stream, for unit tests
    that feed it messages by hand."""

    trace = trace if trace is not None else Trace()
    tree = SeedTree(seed)
    storage = Storage(node_id, tuple(voters), sync_policy=sync_policy)
    return Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=storage,
        rng=tree.stream(node_id, "election"),
        clock=NodeClock(),
        trace=trace,
        options=NodeOptions(**options),
    )


def tick_until_outbox(node: Node, max_ticks=500) -> int:
    """Tick a node until it emits something. Returns ticks taken."""

    for i in range(1, max_ticks + 1):
        node.tick(i)
        if node.outbox:
            return i
    pytest.fail(f"{node.node_id} emitted nothing in {max_ticks} ticks")


def tick_until(node: Node, predicate, max_ticks=500) -> int:
    for i in range(1, max_ticks + 1):
        node.tick(i)
        if predicate(node):
            return i
    pytest.fail(f"{node.node_id} never satisfied the condition in {max_ticks} ticks")


def make_single_leader(node_id="n1", **options) -> Node:
    """A one-node cluster: it elects itself at its first timeout."""

    node = make_node(node_id, voters=(node_id,), **options)
    tick_until(node, lambda n: n.role == "leader")
    return node


@pytest.fixture
def cluster():
    return Cluster(make_schedule())


@pytest.fixture
def repo_root():
    return ROOT
