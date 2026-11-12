"""A peer that walks the lease boundary has to be answerable without a negotiation.

The requirement is a per-peer, bounded, trace-visible quarantine for pre-votes
that are refused by the leader lease while the proposed term keeps rising. What
it must not do is move the lease: SPEC.md 2.7 makes the lease a property of the
node's own clock, and ADR-0009 is why that cannot be delegated to the sender.
"""

from __future__ import annotations

ELECTION_TIMEOUT = 50


def _workspace():
    from pathlib import Path

    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "tidewater").is_dir():
            return candidate
    raise RuntimeError("hidden tests run inside a prepared tidewater workspace")


def _node(node_id="n2", voters=("n1", "n2", "n3", "n4", "n5"), *, term=40):
    from tidewater.clock import NodeClock
    from tidewater.membership import Configuration
    from tidewater.node import Node, NodeOptions
    from tidewater.rng import SeedTree
    from tidewater.storage import Storage
    from tidewater.trace import Trace

    voters = tuple(voters)
    node = Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=Storage(node_id, voters),
        rng=SeedTree(101).stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(election_timeout=ELECTION_TIMEOUT, heartbeat_interval=10),
    )
    node._become_follower(term, leader_id="n1", reason="heartbeat")
    node.last_leader_contact = node.clock.now
    return node


def _prevote(node, src, term):
    from tidewater.messages import RequestVote, RequestVoteResponse

    node.drain_outbox()
    node.receive(src, RequestVote(term=term, candidate_id=src, last_log_index=1,
                                  last_log_term=1, pre_vote=True))
    return [
        (target, message)
        for target, message in node.drain_outbox()
        if isinstance(message, RequestVoteResponse)
    ]


def _events(node, kind=None):
    return [event for event in node.trace if kind is None or event.kind == kind]


def _reasons(node):
    return [event.fields.get("reason") for event in _events(node, "prevote")]


def test_the_lease_refuses_a_pre_vote_while_it_is_fresh():
    node = _node()
    _prevote(node, "n9", 41)
    assert _reasons(node)[-1] == "leader_lease", (
        "the lease is what ADR-0009 is for; the first refusal still has to be the lease"
    )


def test_a_peer_that_walks_the_lease_boundary_is_quarantined():
    node = _node()
    for offset in range(1, 5):
        _prevote(node, "n9", 40 + offset)
    reasons = _reasons(node)
    assert "quarantined" in reasons, (
        "four refused pre-votes at strictly rising terms inside one lease window "
        f"and every answer is still {reasons[-1]!r}; the peer is being told the same "
        "thing forty times over, and the trace cannot show that this is one peer doing it"
    )


def test_a_quarantined_peer_is_refused_without_a_grant_and_the_node_keeps_its_leader():
    node = _node()
    for offset in range(1, 6):
        _prevote(node, "n9", 40 + offset)
    granted = [
        message
        for offset in range(1, 4)
        for _, message in _prevote(node, "n9", 50 + offset)
        if getattr(message, "granted", False)
    ]
    assert not granted, "a quarantined peer was granted a pre-vote"
    assert node.leader_id == "n1", "the node stopped following its leader"
    assert node.current_term == 40, "a refused pre-vote moved the node's term"


def test_the_lease_is_still_judged_only_on_the_nodes_own_clock():
    node = _node()
    before_contact = node.last_leader_contact
    before_deadline = node.election_deadline
    _prevote(node, "n9", 9999)
    assert node.last_leader_contact == before_contact
    assert node.election_deadline == before_deadline, (
        "an incoming pre-vote changed this node's election timing; SPEC.md 2.7 makes "
        "the lease local and ADR-0009 says why"
    )


def test_one_anomalous_pre_vote_is_not_an_attacker():
    node = _node()
    _prevote(node, "n9", 41)
    assert "quarantined" not in _reasons(node), (
        "a node that timed out once was quarantined; the quarantine is for a peer "
        "that repeats the attempt inside one lease window"
    )


def test_a_quarantine_does_not_spread_to_a_peer_that_never_misbehaved():
    node = _node()
    for offset in range(1, 6):
        _prevote(node, "n9", 40 + offset)
    node.leader_id = None
    node.last_leader_contact = node.clock.now - 2 * ELECTION_TIMEOUT
    _, response = _prevote(node, "n3", 41)[0]
    assert response.granted, "an honest peer was refused after another peer was quarantined"


def test_a_quarantine_expires():
    node = _node()
    for offset in range(1, 6):
        _prevote(node, "n9", 40 + offset)
    assert "quarantined" in _reasons(node)
    for tick in range(1, 4 * ELECTION_TIMEOUT + 1):
        node.tick(node.global_tick + 1)
    node.leader_id = None
    node.last_leader_contact = node.clock.now - 2 * ELECTION_TIMEOUT
    _, response = _prevote(node, "n9", 60)[0]
    assert response.granted, (
        "the quarantine is a bounded pause, not a permanent exclusion; a peer that "
        "waits it out and asks honestly has to be heard"
    )


def test_a_real_partition_heal_still_elects_and_commits():
    from tidewater.cluster import Cluster
    from tidewater.schedule import load_schedule

    schedule = load_schedule(str(_workspace() / "schedules" / "partition-heal-storm.json"))
    result = Cluster(schedule, stop_on_violation=True).run()
    assert result.ok, f"the honest case broke: {result.violation}"
    assert len(result.commit_indexes) > 0, "nothing committed"


def test_the_repository_suite_still_passes():
    import subprocess
    import sys

    root = _workspace()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=root, capture_output=True, text=True, timeout=1800,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_twelve_reference_digests_still_match():
    import subprocess
    import sys

    root = _workspace()
    completed = subprocess.run(
        [sys.executable, "tools/reference_traces.py", "--check"],
        cwd=root, capture_output=True, text=True, timeout=1800,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(root / "src")},
    )
    assert completed.returncode == 0, (
        "the honest traffic changed; the twelve digests are the regression test for "
        f"that\n{completed.stdout}\n{completed.stderr}"
    )
