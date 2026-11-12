"""The two halves of the requirement, from the outside.

The first two pass on the code you were given and have to stay passing: the
lease is local, and a peer that times out once is not an attacker. The third is
what is missing — the refusal has to be able to say that the same peer has been
asking all day.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "tidewater").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared tidewater workspace")


ROOT = _root()
sys.path.insert(0, str(ROOT / "src"))

from tidewater.clock import NodeClock  # noqa: E402
from tidewater.membership import Configuration  # noqa: E402
from tidewater.messages import RequestVote, RequestVoteResponse  # noqa: E402
from tidewater.node import Node, NodeOptions  # noqa: E402
from tidewater.rng import SeedTree  # noqa: E402
from tidewater.storage import Storage  # noqa: E402
from tidewater.trace import Trace  # noqa: E402

VOTERS = ("n1", "n2", "n3", "n4", "n5")
ELECTION_TIMEOUT = 50


def follower(node_id="n2", term=40) -> Node:
    node = Node(
        node_id=node_id,
        config=Configuration.of(VOTERS),
        storage=Storage(node_id, VOTERS),
        rng=SeedTree(101).stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(election_timeout=ELECTION_TIMEOUT, heartbeat_interval=10),
    )
    node._become_follower(term, leader_id="n1", reason="heartbeat")
    node.last_leader_contact = node.clock.now
    return node


def prevote(node: Node, src: str, term: int) -> list[RequestVoteResponse]:
    from tidewater.messages import RequestVote as Ask

    node.drain_outbox()
    node.receive(src, Ask(term=term, candidate_id=src, last_log_index=1, last_log_term=1,
                          pre_vote=True))
    return [
        message
        for _, message in node.drain_outbox()
        if isinstance(message, RequestVoteResponse)
    ]


def reasons(node: Node) -> list[str]:
    return [event.fields.get("reason") for event in node.trace if event.kind == "prevote"]


def test_a_fresh_lease_refuses_a_pre_vote():
    node = follower()
    prevote(node, "n9", 41)
    assert reasons(node)[-1] == "leader_lease"


def test_the_lease_does_not_belong_to_the_sender():
    node = follower()
    contact, deadline = node.last_leader_contact, node.election_deadline
    prevote(node, "n9", 9_999)
    assert (node.last_leader_contact, node.election_deadline) == (contact, deadline)


def test_a_peer_that_repeats_the_trick_is_quarantined():
    node = follower()
    for offset in range(1, 5):
        prevote(node, "n9", 40 + offset)
    assert "quarantined" in reasons(node), (
        f"every answer was {reasons(node)[-1]!r}; the trace cannot show that one peer "
        "did all of it, and the peer learns the lease boundary from the refusals"
    )
