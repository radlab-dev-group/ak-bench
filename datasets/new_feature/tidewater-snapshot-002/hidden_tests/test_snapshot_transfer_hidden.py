"""Acceptance tests for the snapshot transfer of ``SPEC.md`` 6.4, 6.5 and 6.6.

The node half of section 6 has landed: a node that writes enough takes a record
at ``last_applied``, compacts behind it and restarts from it. What these tests
accept is the other half — getting that record to a node that can no longer be
replayed forward:

* 6.4 — the leader streams the record ``chunk_size`` bytes at a time, one chunk
  outstanding, and continues from the offset the follower reports rather than
  from its own counter; a transfer keeps the record it opened with, so a newer
  snapshot does not change the bytes already on the wire;
* 6.5 — the follower buffers in volatile memory, answers a chunk it did not ask
  for with the offset it expects and nothing else, and on the last chunk
  installs: the suffix after the boundary survives when the follower holds the
  boundary entry with the boundary term and everything else is discarded, the
  boundary becomes ``base_index``/``base_term``,
  ``commit_index = last_applied = last_included_index``, and the record and the
  log are durable before ``done = True`` is replied;
* 6.6 — a crash in the middle loses the buffer, and the answer to the next chunk
  the follower no longer expects is ``offset = 0``;
* 6.7 — an install is traced as ``snapshot_installed`` and is committed-visible,
  which is a documented digest-visible change: the corpus entry that exercises
  the transfer goes through the generator, into the MANIFEST and through the
  reference-trace tool, as ``docs/runbooks/regenerate-traces.md`` says.

A node alone in a one-voter cluster is used wherever the rule is about a node
and its own record: it commits its own writes, so it has a snapshot worth
sending.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tidewater import snapshot
from tidewater.clock import NodeClock
from tidewater.cluster import Cluster
from tidewater.log import Entry, RaftLog
from tidewater.membership import Configuration
from tidewater.messages import AppendEntries, InstallSnapshot, InstallSnapshotResponse
from tidewater.node import LEADER, Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.schedule import Action, schedule_from_dict
from tidewater.statemachine import Command
from tidewater.storage import Storage
from tidewater.trace import DIGEST_KINDS, Trace

ALONE = ("n1",)
FIVE = ("n1", "n2", "n3", "n4", "n5")
NEW_SCHEDULE = "compaction-catchup"


def repository() -> Path:
    """The workspace root: where ``tools/`` and ``schedules/`` live."""

    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (base / "tools" / "gen_schedules.py").is_file():
            return base
    raise AssertionError("the repository tools are not reachable from the workspace")


def tool(name, *arguments):
    return subprocess.run(
        [sys.executable, str(repository() / "tools" / name), *[str(a) for a in arguments]],
        cwd=str(repository()), capture_output=True, text=True, timeout=600,
    )


def make_node(node_id, voters=ALONE, seed=7, **options):
    tree = SeedTree(seed)
    return Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=Storage(node_id, tuple(voters)),
        rng=tree.stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(**options),
    )


def leader_with_a_snapshot(threshold=4, writes=14, seed=7):
    """A leader that has compacted, so its record is the only copy of the
    prefix, with a state big enough to need more than one chunk."""

    node = make_node("n1", voters=ALONE, seed=seed, compaction_threshold=threshold)
    for _ in range(200):
        node.tick(node.global_tick + 1)
        if node.role == LEADER:
            break
    assert node.role == LEADER, node.describe()
    node.drain_outbox()
    for index in range(writes):
        node.propose(Command("set", f"k{index}", f"value-{index}-{'x' * 16}"))
        node.drain_outbox()
    record = node.storage.snapshot
    assert record is not None, "the leader compacted, so it has a record to send"
    assert len(record.state) > node.snapshot_policy.chunk_size, "the record needs several chunks"
    return node


def stream(leader, peer, *, chunks=None, stop_after=None):
    """Ask the leader for the whole stream, following the offsets its own
    chunks describe, and return the chunks in order."""

    produced = []
    offset = 0
    while True:
        message = snapshot.send_snapshot_chunk(leader, peer, offset)
        produced.append(message)
        if message.done:
            break
        if stop_after is not None and len(produced) >= stop_after:
            break
        offset += len(message.data)
    return produced


def tail_of(boundary_index, boundary_term, count):
    """Entries that start just after a compaction boundary."""

    return [
        Entry(index=boundary_index + step, term=boundary_term,
              command=Command("set", f"tail{step}", str(step)))
        for step in range(1, count + 1)
    ]


def follower_holding(entries=(), base_index=0, base_term=0):
    node = make_node("n2", voters=FIVE, seed=11)
    node.log = RaftLog(entries=entries, base_index=base_index, base_term=base_term)
    return node


def deliver(follower, chunks):
    """Feed chunks to the follower one at a time; return every reply it made."""

    replies = []
    for message in chunks:
        follower.receive("n1", message)
        for destination, reply in follower.drain_outbox():
            assert destination == "n1", "the follower answers the leader on the same channel"
            replies.append(reply)
    return replies


# -- 6.4: the leader's side --------------------------------------------------


def test_the_record_reaches_the_follower_in_chunks_of_the_policy_size():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    chunk_size = leader.snapshot_policy.chunk_size

    chunks = stream(leader, "n2")
    assert b"".join(chunk.data for chunk in chunks) == record.state
    assert all(len(chunk.data) <= chunk_size for chunk in chunks)
    assert [chunk.offset for chunk in chunks] == [
        sum(len(previous.data) for previous in chunks[:position]) for position in range(len(chunks))
    ]
    assert chunks[-1].done and not any(chunk.done for chunk in chunks[:-1])
    for chunk in chunks:
        assert chunk.leader_id == "n1"
        assert chunk.last_included_index == record.last_included_index
        assert chunk.last_included_term == record.last_included_term


def test_the_stream_continues_from_the_offset_the_follower_reports():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    chunk_size = leader.snapshot_policy.chunk_size

    first = snapshot.send_snapshot_chunk(leader, "n2", offset=0)
    assert not first.done
    assert leader.snapshot_transfers["n2"].record.last_included_index == record.last_included_index

    # The follower was ahead of the leader's guess — a chunk it had already
    # thrown away, a duplicate that never arrived. Its answer is what moves.
    snapshot.on_snapshot_ack(leader, "n2", InstallSnapshotResponse(
        term=leader.current_term, follower_id="n2", offset=len(first.data) + 5))
    destination, message = leader.drain_outbox()[-1]
    assert destination == "n2" and isinstance(message, InstallSnapshot)
    assert message.offset == len(first.data) + 5
    assert message.data == record.state[message.offset:message.offset + chunk_size]

    # An answer that names an earlier byte rewinds the stream.
    snapshot.on_snapshot_ack(leader, "n2", InstallSnapshotResponse(
        term=leader.current_term, follower_id="n2", offset=0))
    message = leader.drain_outbox()[-1][1]
    assert message.offset == 0 and message.data == record.state[:chunk_size]


def test_a_transfer_keeps_the_record_it_opened_with():
    leader = leader_with_a_snapshot()
    pinned = leader.storage.snapshot

    first = snapshot.send_snapshot_chunk(leader, "n2", offset=0)
    for index in range(12):
        leader.propose(Command("set", f"later{index}", str(index)))
        leader.drain_outbox()
    assert leader.storage.snapshot.last_included_index != pinned.last_included_index, (
        "the leader has taken a newer record since"
    )

    second = snapshot.send_snapshot_chunk(leader, "n2", offset=len(first.data))
    assert second.last_included_index == pinned.last_included_index
    assert second.last_included_term == pinned.last_included_term
    assert second.data == pinned.state[len(first.data):len(first.data) + leader.snapshot_policy.chunk_size]


def test_a_follower_that_cannot_be_replayed_forward_is_sent_a_snapshot():
    leader = leader_with_a_snapshot(writes=16)
    assert leader.log.base_index > 1
    # Where the bookkeeping for this peer stood before the leader compacted:
    # next_index points at an index the leader no longer holds (SPEC 6.4).
    leader.next_index["n2"] = leader.log.base_index
    leader.drain_outbox()

    leader._send_append("n2")
    queued = [message for _, message in leader.drain_outbox()]
    assert any(isinstance(message, InstallSnapshot) for message in queued), (
        "the next entries the follower wants were compacted away (SPEC 6.4)"
    )


# -- 6.5: the follower's side ------------------------------------------------


def test_an_early_chunk_is_answered_with_the_byte_the_follower_is_waiting_for():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    follower = follower_holding()

    chunks = stream(leader, "n2")
    replies = deliver(follower, chunks[1:2])
    assert len(replies) == 1, "an unasked-for chunk is answered, not ignored"
    assert replies[0].offset == 0 and not replies[0].done
    assert follower.storage.snapshot is None and follower.state_machine.get("k0") is None
    assert follower.commit_index == 0


def test_the_install_keeps_the_suffix_after_a_boundary_it_can_trust():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    boundary = record.last_included_index
    boundary_term = record.last_included_term
    follower = follower_holding(
        entries=[Entry(index=boundary, term=boundary_term, command=Command("set", "boundary", "yes"))]
        + tail_of(boundary, boundary_term, 3),
        base_index=boundary - 1,
        base_term=0 if boundary == 1 else boundary_term,
    )
    assert follower.log.term_at(boundary) == boundary_term, "the follower holds the boundary entry"
    kept_before = [(entry.index, entry.term) for entry in follower.log.entries()]

    replies = deliver(follower, stream(leader, "n2"))
    assert replies[-1].done and replies[-1].offset == len(record.state)

    assert follower.log.base_index == record.last_included_index
    assert follower.log.base_term == record.last_included_term
    assert follower.log.term_at(record.last_included_index) == record.last_included_term
    assert [(entry.index, entry.term) for entry in follower.log.entries()] == kept_before[1:], (
        "the suffix after the boundary survives, the boundary entry itself does not"
    )
    assert follower.commit_index == record.last_included_index
    assert follower.state_machine.last_applied == record.last_included_index

    restored = follower.storage.load_log()
    assert restored.base_index == record.last_included_index and restored.base_term == record.last_included_term


def test_the_install_throws_away_a_log_that_disagrees_with_the_boundary():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot

    wrong_term = follower_holding(
        entries=tail_of(record.last_included_index, record.last_included_term + 1, 2),
        base_index=record.last_included_index,
        base_term=record.last_included_term + 1,
    )
    replies = deliver(wrong_term, stream(leader, "n2"))
    assert replies[-1].done
    assert list(wrong_term.log.entries()) == [], "a suffix whose boundary term differs is not a suffix"
    assert wrong_term.log.base_index == record.last_included_index
    assert wrong_term.log.base_term == record.last_included_term
    assert wrong_term.commit_index == record.last_included_index

    too_short = follower_holding(entries=tail_of(0, 1, 2))
    replies = deliver(too_short, stream(leader, "n2"))
    assert replies[-1].done
    assert list(too_short.log.entries()) == [], "the boundary is past this log, so the snapshot wins"
    assert too_short.commit_index == record.last_included_index
    assert too_short.state_machine.get("k0") is not None, "the state came with the record"


def test_the_record_and_the_log_are_durable_before_the_done_reply():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    follower = follower_holding()

    chunks = stream(leader, "n2")
    replies = deliver(follower, chunks[:-1])
    assert not any(reply.done for reply in replies), "no done before the last byte"
    assert follower.storage.snapshot is None, "nothing is installed until the stream is complete"

    follower.receive("n1", chunks[-1])
    _, reply = follower.drain_outbox()[0]
    assert reply.done and reply.offset == len(record.state)

    durable = follower.storage.durable_view()
    assert durable.snapshot is not None
    assert durable.snapshot.last_included_index == record.last_included_index
    assert durable.snapshot.state == record.state


def test_an_installed_snapshot_is_committed_visible():
    assert "snapshot_installed" in DIGEST_KINDS

    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    follower = follower_holding()
    deliver(follower, stream(leader, "n2"))

    events = follower.trace.of_kind("snapshot_installed")
    assert events, "finishing an install is traced"
    assert events[-1].fields["last_included_index"] == record.last_included_index
    assert events[-1].fields["last_included_term"] == record.last_included_term
    assert any(event.kind == "snapshot_installed" for event in follower.trace.digest_events())


# -- 6.6: a crash in the middle ---------------------------------------------


def test_a_follower_that_crashes_mid_install_asks_to_start_again():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    follower = follower_holding()

    chunks = stream(leader, "n2")
    half = max(1, len(chunks) // 2)
    deliver(follower, chunks[:half])
    assert follower.pending_installs, "the partial install lives in volatile memory"

    follower.crash()
    follower.restart()
    follower.drain_outbox()
    assert not follower.pending_installs, "the buffer did not survive the crash"

    replies = deliver(follower, chunks[half:half + 1])
    assert replies and replies[0].offset == 0, "SPEC 6.6: the first byte is the one it wants now"
    assert not replies[0].done

    deliver(follower, stream(leader, "n2"))
    assert follower.state_machine.last_applied == record.last_included_index
    assert follower.state_machine.get("k0") is not None


def test_a_finished_transfer_puts_the_follower_back_on_the_append_entries_path():
    leader = leader_with_a_snapshot()
    record = leader.storage.snapshot
    follower = follower_holding()

    chunks = stream(leader, "n2")
    for message in chunks[:-1]:
        follower.receive("n1", message)
        _, reply = follower.drain_outbox()[0]
        leader.drain_outbox()
        snapshot.on_snapshot_ack(leader, "n2", reply)
        assert "n2" in leader.snapshot_transfers, "the transfer is still in flight"
        assert leader.match_index.get("n2") is None, "no match before the install is finished"

    follower.receive("n1", chunks[-1])
    _, reply = follower.drain_outbox()[0]
    assert reply.done
    leader.drain_outbox()
    snapshot.on_snapshot_ack(leader, "n2", reply)

    assert "n2" not in leader.snapshot_transfers, "a finished transfer is over"
    assert leader.match_index["n2"] == record.last_included_index
    assert leader.next_index["n2"] == record.last_included_index + 1
    queued = [message for _, message in leader.drain_outbox()]
    assert any(isinstance(message, AppendEntries) for message in queued), "replication resumes"


# -- the cluster this feature exists for ------------------------------------


def catchup_cluster(seed):
    from tidewater.network import NetworkOptions
    from tidewater.schedule import Schedule

    schedule = Schedule(
        name="hidden-catchup",
        nodes=FIVE,
        seed=seed,
        ticks=2600,
        actions=[
            Action(at=1, kind="workload", args={"count": 20, "every": 15, "key_prefix": "a"}),
            Action(at=260, kind="isolate", args={"node": "n2"}),
            Action(at=280, kind="workload", args={"count": 70, "every": 15, "key_prefix": "b"}),
            Action(at=1700, kind="heal", args={}),
            Action(at=1740, kind="workload", args={"count": 30, "every": 15, "key_prefix": "c"}),
        ],
        node_options=NodeOptions(compaction_threshold=18, election_timeout=40, heartbeat_interval=8),
        network_options=NetworkOptions(min_delay=1, max_delay=4, drop_rate=0.03, dup_rate=0.02),
    )
    return Cluster(schedule)


def test_a_node_cut_off_past_the_boundary_comes_back_through_a_snapshot():
    cluster = catchup_cluster(4041)
    result = cluster.run()
    assert result.ok, result.render()

    installs = [event for node in cluster.nodes.values() for event in node.trace.of_kind("snapshot_installed")]
    assert installs, "the isolated node was brought level by a snapshot, not by a replay"
    assert any(event.node == "n2" for event in installs), [event.node for event in installs]

    n2 = cluster.nodes["n2"]
    assert n2.log.base_index > 0, "it resumed from a boundary, not from index 1"
    assert n2.state_machine.get("a0") is not None, "the prefix it never had arrived inside the record"
    assert n2.state_machine.get("c29") is not None, "and it took the work written after it rejoined"

    digests = {node.state_machine.digest() for node in cluster.nodes.values()}
    assert len(digests) == 1, "the cluster agrees on one state"


def test_the_cluster_keeps_committing_while_a_follower_is_brought_level():
    cluster = catchup_cluster(4042)
    result = cluster.run()
    assert result.ok, result.render()
    assert min(result.commit_indexes.values()) > 0, f"somebody stopped committing: {result.commit_indexes}"
    assert min(result.applied.values()) > 0, f"somebody stopped applying: {result.applied}"


# -- 6.7 with the tools: the corpus entry that covers the transfer ----------


def test_the_catchup_run_is_reproducible_and_recorded_in_the_corpus():
    root = repository()
    path = root / "schedules" / f"{NEW_SCHEDULE}.json"
    assert path.is_file(), f"{NEW_SCHEDULE}.json is part of the corpus now"

    raw = path.read_text(encoding="utf-8")
    first = Cluster(schedule_from_dict(json.loads(raw))).run()
    assert first.ok, first.render()
    second = Cluster(schedule_from_dict(json.loads(raw))).run()
    assert first.digest == second.digest, "the same schedule runs the same way twice"

    recorded = (root / "traces" / f"{NEW_SCHEDULE}.digest").read_text(encoding="utf-8")
    fields = dict(line.split(maxsplit=1) for line in recorded.splitlines() if line.strip())
    assert fields["trace_digest"] == first.digest, (
        "the recorded reference digest is the digest of this run: "
        f"{fields['trace_digest']} != {first.digest}"
    )


def test_the_catchup_entry_is_generated_locked_and_digested_by_the_tools():
    """The procedure is part of the deliverable
    (``docs/runbooks/regenerate-traces.md``): the schedule comes from the
    generator, the MANIFEST locks it, and the reference digest comes from the
    tool — none of it written by hand."""

    root = repository()
    manifest = (root / "schedules" / "MANIFEST").read_text(encoding="utf-8")
    path = root / "schedules" / f"{NEW_SCHEDULE}.json"
    assert path.is_file()

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    line = next((line for line in manifest.splitlines() if line.strip().endswith(f"{NEW_SCHEDULE}.json")), None)
    assert line is not None, f"{NEW_SCHEDULE}.json has no MANIFEST line"
    assert line.split()[0] == digest, f"MANIFEST line {line!r} does not lock {digest}"

    checked = tool("gen_schedules.py", "--check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert f"{NEW_SCHEDULE}:" in tool("gen_schedules.py", "--list").stdout

    assert (root / "traces" / f"{NEW_SCHEDULE}.digest").is_file(), "the reference digest is recorded"
    reference = tool("reference_traces.py", "--check", "--only", NEW_SCHEDULE)
    assert reference.returncode == 0, reference.stdout + reference.stderr
    assert "DigestMismatch" not in reference.stdout
