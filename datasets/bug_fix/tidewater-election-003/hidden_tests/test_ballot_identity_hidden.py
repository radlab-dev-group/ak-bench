"""Witness scenarios for a tally that counts machines that never answered.

The signature is the family's own — ``election_safety``, ``term N has two
leaders`` — and none of the ballot rules of ``ADR-0013`` are being broken
here: every answer counted is a grant, in the right term, delivered to a node
that is a candidate. What is wrong is *whom* the tally credits. ``SPEC.md``
4.2 and ``docs/incidents/INC-0008``: a majority is counted over the voters of
the configuration, and the set that goes into the arithmetic is the set of
voters, named by the protocol.

A voter's answer reaches a candidate through another machine sometimes (a
link that forwards, a proxy, a request that came back by the way it came). The
machine the answer travelled through did not vote.
"""

import pytest

from tidewater.clock import NodeClock
from tidewater.invariants import InvariantMonitor, SafetyViolation
from tidewater.membership import Configuration
from tidewater.messages import RequestVote, RequestVoteResponse
from tidewater.node import CANDIDATE, LEADER, Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.storage import Storage
from tidewater.trace import Trace

FAST = {"election_timeout": 5, "heartbeat_interval": 1}
QUINT = ("p", "y", "q", "r", "s")


def make_node(node_id, voters=QUINT, seed=7, **options):
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


def ballot(term, voter, granted=True):
    return RequestVoteResponse(term=term, voter_id=voter, granted=granted)


def grant_through(candidate, voter_id, term, envelope_from, voters=QUINT, seed=11):
    """The voter's grant, delivered in somebody else's envelope."""

    voter = make_node(voter_id, voters=voters, seed=seed)
    voter.receive(candidate.node_id, RequestVote(term=term, candidate_id=candidate.node_id,
                                                 last_log_index=0, last_log_term=0))
    for index, (destination, message) in enumerate(voter.outbox):
        if destination == candidate.node_id and isinstance(message, RequestVoteResponse):
            reply = voter.outbox.pop(index)[1]
            assert reply.granted, f"{voter_id} should grant term {term}"
            candidate.receive(envelope_from, reply)
            return voter
    raise AssertionError(f"{voter_id} never answered {candidate.node_id}")


def stays_clean(*nodes, tick=1):
    try:
        InvariantMonitor().check(list(nodes), tick)
    except SafetyViolation as violation:
        pytest.fail(f"safety monitor: {violation}")


def test_a_ballot_is_credit_to_the_voter_who_named_herself_in_it():
    """One grant, carried by a second machine: the tally holds the voter and
    the candidate, and nobody else."""

    p = make_node("p", seed=3, pre_vote=False)
    become(p, CANDIDATE)

    carrier = make_node("r", seed=4)  # alive, in the configuration, silent
    grant_through(p, "q", 1, envelope_from="r")

    assert p.votes == {"p", "q"}, f"{sorted(p.votes)} were credited with one ballot"
    assert p.role == CANDIDATE, "two of five is not a majority"
    stays_clean(p, carrier)


def test_one_ballot_carried_by_two_machines_is_still_one_ballot():
    """The same grant arrives twice, once directly and once forwarded. It is
    one voter and it is counted once."""

    p = make_node("p", seed=5, pre_vote=False)
    become(p, CANDIDATE)

    grant_through(p, "q", 1, envelope_from="q")
    grant_through(p, "q", 1, envelope_from="s")

    assert p.votes == {"p", "q"}, f"one voter was counted twice: {sorted(p.votes)}"
    assert p.role == CANDIDATE, "two of five is not a majority"


def test_a_candidate_must_not_be_elected_by_the_machines_an_answer_came_through():
    """The safety half: q's grant reaches p through r, and r votes for the
    rival. If the carrier counts, p and the rival lead the same term."""

    p = make_node("p", seed=6, pre_vote=False)
    y = make_node("y", seed=7, pre_vote=False)
    become(p, CANDIDATE)
    become(y, CANDIDATE)
    assert p.current_term == y.current_term == 1

    carrier = grant_through(p, "q", 1, envelope_from="r")

    # r and s now cast the only two real ballots still available in term 1.
    for voter_id in ("r", "s"):
        grant_through(y, voter_id, 1, envelope_from=voter_id)
    stays_clean(p, y, carrier)
    assert p.role == CANDIDATE, "p holds one ballot from someone else"
    assert y.role == LEADER, "y holds three ballots of five"
    assert p.role != LEADER, "p led a term the machines in its tally never gave it"


def test_the_honest_path_still_elects():
    """Control: ballots handed over directly still add up."""

    p = make_node("p", seed=8, pre_vote=False)
    become(p, CANDIDATE)
    q = grant_through(p, "q", 1, envelope_from="q")
    assert p.role == CANDIDATE
    r = grant_through(p, "r", 1, envelope_from="r")
    assert p.role == LEADER, "p, q and r are a majority of five"
    stays_clean(p, q, r)
