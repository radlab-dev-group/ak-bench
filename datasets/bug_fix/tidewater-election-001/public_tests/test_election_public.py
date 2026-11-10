"""Complaints about the elections, as the operators wrote them.

Four reports from two weeks of a small cluster, plus one report that says
nothing unusual happened. They say what the cluster did and what it should
have done; they do not say which part of it was wrong.

Everything is driven through the seams the repository suite uses: a node is
fed messages and ticks, and the safety monitor is asked whether what
happened is allowed.
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

QUICK = {"election_timeout": 5, "heartbeat_interval": 1}
TRIO = ("p", "q", "w")
FIVE = ("p", "q", "w1", "w2", "w3")


def machine(node_id, voters, seed=1, disk="always", **override):
    settings = dict(QUICK)
    settings.update(override)
    tree = SeedTree(seed)
    return Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=Storage(node_id, tuple(voters), sync_policy=disk),
        rng=tree.stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(**settings),
    )


def poll(node, role, limit=200):
    for _ in range(limit):
        if node.role == role:
            return node
        node.tick(node.global_tick + 1)
    raise AssertionError(f"{node.node_id} never became {role}: {node.describe()}")


def next_term(node, term):
    while node.current_term < term:
        node.tick(node.global_tick + 1)
    node.drain_outbox()
    return node


def ask(voter, candidate_id, term):
    """Ask ``voter`` for its ballot in ``term`` and take the answer it gives."""

    voter.receive(candidate_id, RequestVote(
        term=term, candidate_id=candidate_id, last_log_index=0, last_log_term=0))
    for index, (destination, message) in enumerate(voter.outbox):
        if destination == candidate_id and isinstance(message, RequestVoteResponse):
            return voter.outbox.pop(index)[1]
    raise AssertionError(f"{voter.node_id} never answered {candidate_id}")


def take_part(voter_id, candidate, term, voters=FIVE, seed=20, disk="always"):
    """A machine joins the election: it is asked, it answers, the answer arrives."""

    voter = machine(voter_id, voters, seed=seed, disk=disk)
    candidate.receive(voter_id, ask(voter, candidate.node_id, term))
    return voter


def converse(candidate, voters):
    """One round of conversation: every request the candidate made to a voter
    is answered by that voter and the answer is delivered back."""

    for destination, message in candidate.drain_outbox():
        voter = voters.get(destination)
        if voter is None:
            continue
        if isinstance(message, RequestVote):
            voter.receive(candidate.node_id, message)
        for reply_to, reply in voter.drain_outbox():
            if reply_to == candidate.node_id:
                candidate.receive(voter.node_id, reply)
    return candidate


def stays_clean(*nodes, tick=1):
    try:
        InvariantMonitor().check(list(nodes), tick)
    except SafetyViolation as violation:
        pytest.fail(f"the cluster did this: {violation}")


def test_only_one_of_the_machines_that_raced_for_the_job_ends_up_running_the_cluster():
    """Two of three machines timed out at the same moment. One cluster."""

    p = machine("p", TRIO, seed=2, pre_vote=False)
    q = machine("q", TRIO, seed=3, pre_vote=False)
    poll(p, CANDIDATE)
    poll(q, CANDIDATE)
    assert p.current_term == q.current_term == 1

    # They notice each other. Both are still standing, so both answer the same way.
    q.receive("p", ask(p, "q", 1))
    p.receive("q", ask(q, "p", 1))

    w = take_part("w", p, 1, voters=TRIO)

    assert not (p.role == LEADER and q.role == LEADER), "two leaders in one term"
    stays_clean(p, q, w)


def test_an_answer_to_an_election_that_has_already_closed_elects_nobody():
    """The request went out in term one and the answer came back in term two.
    Term two keeps its own books."""

    p = machine("p", FIVE, seed=4, pre_vote=False)
    poll(p, CANDIDATE)
    early = machine("w1", FIVE, seed=5)
    envelope = ask(early, "p", 1)
    assert envelope.granted
    p.receive("w1", envelope)
    assert p.role == CANDIDATE and p.current_term == 1, "two of five is not an election"

    next_term(p, 2)
    take_part("w2", p, 2)
    assert p.role == CANDIDATE, "one ballot from someone else is not an election"

    q = machine("q", FIVE, seed=6, pre_vote=False)
    poll(q, CANDIDATE)
    next_term(q, 2)
    for voter_id in ("w1", "w3"):
        peer = machine(voter_id, FIVE, seed=7)
        reply = ask(peer, "q", 2)
        assert reply.granted, f"{voter_id} owes term two a ballot"
        q.receive(voter_id, reply)
    assert q.role == LEADER, "three ballots of five is an election"

    p.receive("w1", envelope)  # the late answer from term one finally arrives
    assert p.role != LEADER, "term one closed a long time ago"
    stays_clean(p, q)


def test_a_voter_that_reboots_in_the_middle_of_an_election_is_not_asked_twice():
    """The machine that said yes lost power before it could remember saying yes."""

    p = machine("p", TRIO, seed=8, pre_vote=False)
    q = machine("q", TRIO, seed=9, pre_vote=False)
    poll(p, CANDIDATE)
    poll(q, CANDIDATE)

    w = machine("w", TRIO, seed=10, disk="explicit")
    first = ask(w, "p", 1)
    assert first.granted, "an honest voter answers the first request of a term"
    p.receive("w", first)
    assert p.role == LEADER, "two of three ballots are a majority"

    w.crash()
    w.restart()
    second = ask(w, "q", 1)
    q.receive("w", second)

    assert not (p.role == LEADER and q.role == LEADER), "a reboot must not buy a second ballot"
    stays_clean(p, q, w)


def test_a_second_election_is_judged_only_on_the_ballots_of_the_second_election():
    """The first election failed. Its ballots burned with it."""

    p = machine("p", FIVE, seed=11, pre_vote=False)
    poll(p, CANDIDATE)
    take_part("w1", p, 1)
    assert p.role == CANDIDATE and p.current_term == 1

    next_term(p, 2)
    take_part("w2", p, 2)
    assert p.role == CANDIDATE, "the second term holds one ballot from someone else"

    q = machine("q", FIVE, seed=12, pre_vote=False)
    poll(q, CANDIDATE)
    next_term(q, 2)
    for voter_id in ("w1", "w3"):
        peer = machine(voter_id, FIVE, seed=13)
        reply = ask(peer, "q", 2)
        assert reply.granted
        q.receive(voter_id, reply)
    assert q.role == LEADER

    assert p.role != LEADER, "the second election counted ballots it was never given"
    stays_clean(p, q)


def test_a_quiet_cluster_elects_one_leader_and_keeps_it():
    """The boring report: nothing unusual happened and the cluster is fine."""

    p = machine("p", TRIO, seed=14)
    voters = {name: machine(name, TRIO, seed=index) for index, name in enumerate(("q", "w"))}
    for _ in range(80):
        p.tick(p.global_tick + 1)
        converse(p, voters)
        if p.role == LEADER:
            break
    assert p.role == LEADER, p.describe()
    for _ in range(10):
        p.tick(p.global_tick + 1)
        converse(p, voters)
    assert p.role == LEADER, "a leader that nothing disturbed keeps the job"
    stays_clean(p, *voters.values())
