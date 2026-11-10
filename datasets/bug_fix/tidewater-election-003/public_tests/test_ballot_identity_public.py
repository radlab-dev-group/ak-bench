"""Complaints about who was counted as having voted.

The wall says `term 1 has two leaders`, and the runbook for that line says to
look at the ballots. When the operators did, they found a candidate elected
with a tally that named machines which had answered nobody — one grant,
several machines, and a term in which every answer was legal. The reports
below are what they could reproduce.
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
FIVE = ("p", "y", "q", "r", "s")


def machine(node_id, voters=FIVE, seed=7, **options):
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


def until_candidate(node, limit=200):
    for _ in range(limit):
        if node.role == CANDIDATE:
            return node
        node.tick(node.global_tick + 1)
    raise AssertionError(f"{node.node_id} never stood: {node.describe()}")


def answer_behind(voter_id, candidate, term, delivered_by, seed=11):
    """``voter_id`` answers ``candidate``; the answer is handed over by
    ``delivered_by``, the machine the link went through."""

    voter = machine(voter_id, seed=seed)
    voter.receive(candidate.node_id, RequestVote(term=term, candidate_id=candidate.node_id,
                                                 last_log_index=0, last_log_term=0))
    for index, (destination, message) in enumerate(voter.outbox):
        if destination == candidate.node_id and isinstance(message, RequestVoteResponse):
            candidate.receive(delivered_by, voter.outbox.pop(index)[1])
            return voter
    raise AssertionError(f"{voter_id} never answered {candidate.node_id}")


def stays_clean(*nodes, tick=1):
    try:
        InvariantMonitor().check(list(nodes), tick)
    except SafetyViolation as violation:
        pytest.fail(f"the cluster did this: {violation}")


def test_a_candidate_needs_answers_from_the_machines_in_its_tally():
    """p was reported elected on the strength of a ballot from q, carried by
    r. Two of the five names in that tally had answered nobody."""

    p = machine("p", seed=3, pre_vote=False)
    until_candidate(p)
    carrier = machine("r", seed=4)

    answer_behind("q", p, 1, delivered_by="r")

    assert p.role == CANDIDATE, "a machine that carried an answer is not a machine that voted"
    stays_clean(p, carrier)


def test_the_same_ballot_handed_over_twice_elects_nobody_twice():
    """q's grant came to p directly and again through s. The cluster counted
    two machines."""

    p = machine("p", seed=5, pre_vote=False)
    until_candidate(p)

    answer_behind("q", p, 1, delivered_by="q")
    answer_behind("q", p, 1, delivered_by="s")

    assert p.role == CANDIDATE, "one machine, one ballot"


def test_two_candidates_elected_from_one_real_ballot_apiece_is_two_leaders_in_one_term():
    """The report the on-call opened: term 1 with two leaders. q's grant
    reached p through r, and r then voted for y."""

    p = machine("p", seed=6, pre_vote=False)
    y = machine("y", seed=7, pre_vote=False)
    until_candidate(p)
    until_candidate(y)

    carrier = answer_behind("q", p, 1, delivered_by="r")
    for voter_id in ("r", "s"):
        answer_behind(voter_id, y, 1, delivered_by=voter_id)

    assert not (p.role == LEADER and y.role == LEADER), "one term, one leader"
    stays_clean(p, y, carrier)


def test_three_machines_that_actually_answered_still_elect_one():
    """The healthy report: three real ballots, one leader."""

    p = machine("p", seed=8, pre_vote=False)
    until_candidate(p)
    q = answer_behind("q", p, 1, delivered_by="q")
    r = answer_behind("r", p, 1, delivered_by="r")
    assert p.role == LEADER, "three of five is a majority"
    stays_clean(p, q, r)
