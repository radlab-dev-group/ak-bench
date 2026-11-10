"""Witness scenarios for the five cooperating election regressions.

Every witness targets one regression in isolation: the base repository passes
it and the mutated repository fails it. All five fail on the same contract —
``SPEC.md`` 2.5, 2.6 and 5.2, gathered in ``ADR-0012`` — and they arrive in
two pairs and a single:

* pair one, one ballot per term: the answer a standing candidate gives a rival
  (part 01) and the answer a candidate counts from a term that is over
  (part 02). Repairing one half of the pair leaves the other raising the very
  same ``election_safety`` line;
* pair two, the state an election may count on: the sync a granted vote owes
  its reply (part 03) and the sync function itself (part 05). Putting the
  missing call back without reading what the call writes re-raises the same
  violation;
* part 04 stands alone: the tally of a failed election burns with it.

The nodes are driven by hand, exactly as the repository suite drives a single
node: messages go in through ``receive``, answers come out of the outbox, and
the safety monitor is asked after every scenario. The last two scenarios run
the corpus so that a value produced early in the session (a run digest) has to
still be true at the end of it.
"""

import json
from pathlib import Path

import pytest

from tidewater.clock import NodeClock
from tidewater.cluster import Cluster
from tidewater.invariants import InvariantMonitor, SafetyViolation
from tidewater.membership import Configuration
from tidewater.messages import RequestVote, RequestVoteResponse
from tidewater.node import CANDIDATE, LEADER, Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.schedule import schedule_from_dict
from tidewater.storage import Storage
from tidewater.trace import Trace

FAST = {"election_timeout": 5, "heartbeat_interval": 1}

#: three voters, majority two: a standing candidate, a rival, one honest voter
RIVAL = ("x", "y", "a")
#: five voters, majority three: two candidates and three honest voters
STORM = ("x", "s", "a", "b", "c")


def make_node(node_id, voters=RIVAL, seed=7, sync_policy="always", **options):
    settings = dict(FAST)
    settings.update(options)
    tree = SeedTree(seed)
    storage = Storage(node_id, tuple(voters), sync_policy=sync_policy)
    return Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=storage,
        rng=tree.stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(**settings),
    )


def become(node, role, max_ticks=200):
    for _ in range(max_ticks):
        if node.role == role:
            return node
        node.tick(node.global_tick + 1)
    raise AssertionError(f"{node.node_id} never reached {role}: {node.describe()}")


def advance_term(node, term, max_ticks=600):
    while node.current_term < term:
        node.tick(node.global_tick + 1)
        if node.global_tick > max_ticks:
            raise AssertionError(f"{node.node_id} stuck at term {node.current_term}")
    return node


def vote(term, candidate, **fields):
    return RequestVote(term=term, candidate_id=candidate,
                       last_log_index=int(fields.get("index", 0)),
                       last_log_term=int(fields.get("term_l", 0)))


def answer(term, voter, granted=True):
    return RequestVoteResponse(term=term, voter_id=voter, granted=granted)


def take_reply(node, to):
    """Pop the one protocol answer the node addressed to ``to``."""

    for index, (destination, message) in enumerate(node.outbox):
        if destination == to and isinstance(message, RequestVoteResponse):
            return node.outbox.pop(index)[1]
    raise AssertionError(f"{node.node_id} sent no vote response to {to}")


def honest_grant(voter_id, candidate_node, term, voters=STORM, seed=11):
    """A real node adopts ``term``, grants its ballot, and the grant is delivered."""

    voter = make_node(voter_id, voters=voters, seed=seed)
    voter.receive(candidate_node.node_id, vote(term, candidate_node.node_id))
    reply = take_reply(voter, candidate_node.node_id)
    assert reply.granted and reply.term == term, f"{voter_id} should grant term {term}"
    candidate_node.receive(voter.node_id, reply)
    return voter


def assert_one_leader(*nodes, tick=1):
    try:
        InvariantMonitor().check(list(nodes), tick)
    except SafetyViolation as violation:
        pytest.fail(f"safety monitor: {violation}")


def two_rivals(voters):
    """Two nodes that have each timed out into the same term and voted for themselves."""

    left = make_node("x", voters=voters, seed=3, pre_vote=False)
    right = make_node("y", voters=voters, seed=4, pre_vote=False)
    become(left, CANDIDATE)
    become(right, CANDIDATE)
    assert left.current_term == right.current_term == 1
    assert left.role == right.role == CANDIDATE
    assert left.voted_for == "x" and right.voted_for == "y"
    return left, right


# ------------------------------------------------------------------ witnesses


def test_witness_01_a_candidate_answers_a_rival_with_a_denial():
    """A candidate asked about a rival in its own term answers: no. I am standing."""

    x, y = two_rivals(RIVAL)

    x.receive("y", vote(1, "y"))
    from_x = take_reply(x, "y")
    y.receive("x", from_x)

    # a answers x honestly; two ballots of three are a majority.
    a1 = honest_grant("a", x, 1, voters=RIVAL)

    assert_one_leader(x, y, a1)
    assert not (x.role == LEADER and y.role == LEADER), "one term, one leader"


def test_witness_02_a_reply_from_a_finished_term_is_not_a_vote():
    """A grant that arrives after its term is over is a late post, not a ballot."""

    x = make_node("x", voters=STORM, seed=5, pre_vote=False)
    become(x, CANDIDATE)
    assert x.current_term == 1

    # Term 1: one peer answers and x counts it — two of five, not a majority.
    n3 = make_node("a", voters=STORM, seed=6)
    n3.receive("x", vote(1, "x"))
    delayed = take_reply(n3, "x")
    assert delayed.granted and delayed.term == 1
    x.receive("a", delayed)
    assert x.role == CANDIDATE and x.current_term == 1

    # Term 2 begins from one ballot: its own.
    advance_term(x, 2)
    assert x.role == CANDIDATE
    x.drain_outbox()
    n4 = honest_grant("b", x, 2, voters=STORM)
    assert x.role == CANDIDATE, "two real ballots of five are not a majority"

    # A real leader of term two rises meanwhile: s with a and c.
    s = make_node("s", voters=STORM, seed=8, pre_vote=False)
    become(s, CANDIDATE)
    advance_term(s, 2)
    s.drain_outbox()
    for voter_id in ("a", "c"):
        peer = make_node(voter_id, voters=STORM, seed=9)
        peer.receive("s", vote(2, "s"))
        reply = take_reply(peer, "s")
        assert reply.granted, f"{voter_id} owes term 2 a fresh ballot"
        s.receive(voter_id, reply)
    assert s.role == LEADER, "three real ballots are a majority"

    # The answer of the finished term arrives now. It is not a vote.
    x.receive("a", delayed)
    assert_one_leader(x, s)
    assert x.role != LEADER, "a grant from a finished term was counted"


def test_witness_03_a_granted_vote_is_durable_before_the_reply_leaves():
    """A vote whose reply has left must already be on disk, or the crash undeclares it."""

    x, y = two_rivals(RIVAL)
    voter = make_node("a", voters=RIVAL, sync_policy="explicit")

    voter.receive("x", vote(1, "x"))
    first = take_reply(voter, "x")
    assert first.granted, "a healthy voter grants the first ballot of a term"
    x.receive("a", first)
    assert x.role == LEADER, "two of three ballots elect"

    # The voter who already answered dies and comes back. Term one is over for
    # him: the ballot is in his hand and stays there.
    voter.crash()
    voter.restart()
    voter.receive("y", vote(1, "y"))
    second = take_reply(voter, "y")
    y.receive("a", second)

    assert_one_leader(x, y, voter)
    assert not second.granted, "the ballot a already gave in term 1 is not a second ballot"
    assert not (x.role == LEADER and y.role == LEADER), "a crash must not undeclare a vote"


def test_witness_04_a_new_election_counts_only_this_election():
    """The tally of a failed election burns with it; the next term starts alone."""

    x = make_node("x", voters=STORM, seed=5, pre_vote=False)
    become(x, CANDIDATE)
    a1 = honest_grant("a", x, 1, voters=STORM)
    assert x.role == CANDIDATE and x.current_term == 1, "two of five is not a majority"

    advance_term(x, 2)
    assert x.role == CANDIDATE
    x.drain_outbox()

    # A leader of term two rises for real: s, with a and c.
    s = make_node("s", voters=STORM, seed=8, pre_vote=False)
    become(s, CANDIDATE)
    advance_term(s, 2)
    s.drain_outbox()
    for voter_id in ("a", "c"):
        peer = make_node(voter_id, voters=STORM, seed=9)
        peer.receive("s", vote(2, "s"))
        reply = take_reply(peer, "s")
        assert reply.granted
        s.receive(voter_id, reply)
    assert s.role == LEADER

    # Term two, one real ballot for x. Anything carried over from term one is
    # a vote this election was never given, and a second leader of this term.
    b1 = honest_grant("b", x, 2, voters=STORM)
    assert_one_leader(x, s, b1)
    assert x.role != LEADER, "a tally was carried over from the failed election"


def test_witness_05_the_sync_call_writes_every_field_a_crash_is_told_to_find():
    """``sync`` makes the persistent state durable — every field of it, not the convenient half."""

    storage = Storage("a", RIVAL, sync_policy="explicit")
    storage.set_term(4, "candidate")
    assert storage.sync() is True
    durable = storage.durable_view()
    assert durable.current_term == 4, "the term reached the disk"
    assert durable.voted_for == "candidate", "the vote rode with the term or the crash loses it"

    # And the protocol consequence: a crash after a granted ballot must not
    # hand the same term a second vote.
    x, y = two_rivals(RIVAL)
    voter = make_node("a", voters=RIVAL, sync_policy="explicit")
    voter.receive("x", vote(1, "x"))
    first = take_reply(voter, "x")
    assert first.granted
    assert voter.storage.durable_view().voted_for == "x", "the reply left with the ballot on disk"
    x.receive("a", first)
    assert x.role == LEADER, "x holds two of three ballots"

    voter.crash()
    voter.restart()
    assert voter.voted_for == "x", "the crash found the ballot where the reply said it was"
    voter.receive("y", vote(1, "y"))
    second = take_reply(voter, "y")
    y.receive("a", second)

    assert not (x.role == LEADER and y.role == LEADER), "sync undeclared the recorded vote"
    assert_one_leader(x, y, voter)


# ------------------------------------------------------------ multi-phase runs


def test_the_storm_of_overlapping_timeouts_keeps_one_leader_per_term():
    """Five nodes, no pre-vote, every answer delayed one tick: safety still holds."""

    nodes = {name: make_node(name, voters=STORM, seed=index, pre_vote=False)
             for index, name in enumerate(STORM)}
    pending = []  # (deliver_at_tick, src, dst, message)
    for tick in range(1, 400):
        for name, node in nodes.items():
            node.tick(tick)
        due, pending = [item for item in pending if item[0] <= tick], [item for item in pending if item[0] > tick]
        for _, src, dst, message in due:
            if nodes[dst].alive:
                nodes[dst].receive(src, message)
        for name, node in nodes.items():
            for dst, message in node.drain_outbox():
                if isinstance(message, RequestVoteResponse):
                    pending.append((tick + 1, name, dst, message))
                else:
                    nodes[dst].receive(name, message)
        try:
            InvariantMonitor().check(list(nodes.values()), tick)
        except SafetyViolation as violation:
            pytest.fail(f"the storm broke safety at tick {tick}: {violation}")
    live = [node for node in nodes.values() if node.role == LEADER]
    assert len({node.current_term for node in live}) == len(live), "one leader per term"


def test_a_long_storm_run_of_the_corpus_is_reproducible_and_quiet():
    """The reference storm, run twice: the digest found in the first run is
    the value the second half of the session is scored against."""

    def locate(name):
        for base in [Path.cwd(), *Path(__file__).resolve().parents]:
            candidate = base / "schedules" / name
            if candidate.is_file():
                return candidate
            candidate = base / "datasets" / "_sources" / "tidewater" / "schedules" / name
            if candidate.is_file():
                return candidate
        raise AssertionError("the schedule corpus is not reachable from the workspace")

    path = locate("partition-heal-storm.json")
    schedule = schedule_from_dict(json.loads(path.read_text(encoding="utf-8")))
    first = Cluster(schedule).run()
    assert first.ok, first.render()
    committed = dict(first.commit_indexes)

    second = Cluster(schedule_from_dict(json.loads(path.read_text(encoding="utf-8")))).run()
    assert second.digest == first.digest, "a run is a pure function of (schedule, seed, code)"
    assert second.commit_indexes == committed, "the same run commits the same indexes"
    assert sum(committed.values()) > 0, "the storm does make progress"
