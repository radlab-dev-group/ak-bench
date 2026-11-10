"""Witness scenarios for the majority-arithmetic regression.

One defect, four ways of asking for the number. The rule is in ``SPEC.md``
4.2 and repeated in ``docs/incidents/INC-0008``: a majority is
``size // 2 + 1`` of the voters of the configuration, and
``Configuration.has_majority`` is the only place that does the arithmetic.
The rule coincides with "half, rounded up" for every odd size, so every
scenario here is about an even configuration — which is exactly the shape a
four-node cluster, and every joint configuration in ``SPEC.md`` 7, has.
"""

import pytest

from tidewater.clock import NodeClock
from tidewater.cluster import Cluster
from tidewater.invariants import InvariantMonitor, SafetyViolation
from tidewater.membership import Configuration
from tidewater.messages import AppendEntriesResponse, RequestVote, RequestVoteResponse
from tidewater.network import NetworkOptions
from tidewater.node import CANDIDATE, LEADER, Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.schedule import Action, Schedule
from tidewater.statemachine import Command
from tidewater.storage import Storage
from tidewater.trace import Trace

FAST = {"election_timeout": 6, "heartbeat_interval": 1}
QUAD = ("p", "q", "r", "s")
QUINT = ("p", "q", "a", "b", "c")


def make_node(node_id, voters=QUAD, seed=7, **options):
    settings = dict(FAST)
    settings.update(options)
    tree = SeedTree(seed)
    return Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=Storage(node_id, tuple(voters)),
        rng=tree.stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(**settings),
    )


def become(node, role, limit=200):
    for _ in range(limit):
        if node.role == role:
            return node
        node.tick(node.global_tick + 1)
    raise AssertionError(f"{node.node_id} never reached {role}: {node.describe()}")


def grant(voter_id, candidate, term, voters=QUAD, seed=11):
    voter = make_node(voter_id, voters=voters, seed=seed)
    voter.receive(candidate.node_id, RequestVote(term=term, candidate_id=candidate.node_id,
                                                 last_log_index=0, last_log_term=0))
    for index, (destination, message) in enumerate(voter.outbox):
        if destination == candidate.node_id and isinstance(message, RequestVoteResponse):
            reply = voter.outbox.pop(index)[1]
            candidate.receive(voter_id, reply)
            return voter
    raise AssertionError(f"{voter_id} never answered {candidate.node_id}")


def stays_clean(*nodes, tick=1):
    try:
        InvariantMonitor().check(list(nodes), tick)
    except SafetyViolation as violation:
        pytest.fail(f"safety monitor: {violation}")


def test_the_arithmetic_is_the_configurations_own_for_every_size():
    """``has_majority`` answers ``majority_size``, and nothing else, for every
    configuration size the contract defines."""

    for size in range(1, 8):
        voters = tuple(sorted(f"v{n}" for n in range(size)))
        config = Configuration.of(voters)
        needed = config.majority_size
        assert needed == size // 2 + 1, voters
        for taken in range(size + 1):
            acks = voters[:taken]
            assert config.has_majority(acks) is (taken >= needed), (voters, acks)


def test_a_four_node_cluster_counts_three_ballots_and_not_two():
    """Half of four is two, and two of four is not a majority of four."""

    p = make_node("p", voters=QUAD, seed=3, pre_vote=False)
    become(p, CANDIDATE)
    assert p.current_term == 1

    q = grant("q", p, 1)
    assert p.role == CANDIDATE, "two of four is half, and half is not a majority"
    stays_clean(p, q)

    r = grant("r", p, 1)
    assert p.role == LEADER, "three of four is a majority"
    stays_clean(p, q, r)


def test_the_quorum_of_a_four_node_cluster_is_three_in_both_directions():
    """The same number decides votes and commits: two copies of a write in a
    four-voter cluster are not a majority, three are."""

    p = make_node("p", voters=QUAD, seed=4, pre_vote=False)
    become(p, CANDIDATE)
    grant("q", p, 1)
    grant("r", p, 1)
    assert p.role == LEADER
    p.drain_outbox()

    entry = p.propose(Command("set", "key", "value"))
    assert p.commit_index == 0, "only the leader holds the entry"

    p.receive("q", AppendEntriesResponse(term=1, follower_id="q", success=True, match_index=entry.index))
    assert p.commit_index == 0, "the leader and one follower are two of four"

    p.receive("r", AppendEntriesResponse(term=1, follower_id="r", success=True, match_index=entry.index))
    assert p.commit_index == entry.index, "three of four is a majority"


def test_two_halves_of_a_four_node_cluster_elect_nobody():
    """A four-voter cluster split 2 and 2 has no majority on either side, so
    it has no leader at all until the partition heals."""

    schedule = Schedule(
        name="quad-split",
        nodes=QUAD,
        seed=5,
        ticks=400,
        actions=[Action(at=1, kind="partition", args={"groups": [["p", "q"], ["r", "s"]]})],
        node_options=NodeOptions(**FAST),
        network_options=NetworkOptions(max_delay=2),
    )
    cluster = Cluster(schedule)
    result = cluster.run()
    assert result.ok, result.render()
    leaders = cluster.live_leaders()
    assert not leaders, f"a half of four must not elect: {[n.describe() for n in leaders]}"


def test_a_four_node_cluster_with_three_reachable_voters_elects_one_leader():
    """The same schedule with a 3 and 1 split elects exactly one leader, and
    the minority machine cannot join it in."""

    schedule = Schedule(
        name="quad-three-and-one",
        nodes=QUAD,
        seed=6,
        ticks=400,
        actions=[Action(at=1, kind="partition", args={"groups": [["p", "q", "r"], ["s"]]})],
        node_options=NodeOptions(**FAST),
        network_options=NetworkOptions(max_delay=2),
    )
    cluster = Cluster(schedule)
    result = cluster.run()
    assert result.ok, result.render()
    leaders = cluster.live_leaders()
    assert len(leaders) == 1, [n.describe() for n in leaders]
    assert leaders[0].node_id in {"p", "q", "r"}, leaders[0].describe()
