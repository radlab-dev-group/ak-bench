"""Acceptance tests for the snapshot and compaction surface of ``SPEC.md`` 6.

The repository declares the feature and refuses to do it; these tests are the
acceptance rule, plus the procedure the feature has to be landed with. In
order:

* 6.1/6.2 — the trigger, the record, and the order in which the record is made
  durable relative to the log it compacts;
* 6.3 — the compaction boundary: its term is kept, it never passes
  ``last_applied``, and log matching at the boundary behaves as for an entry;
* 6.6/5.4 — a node that restarts with a snapshot loads the state machine from
  it, starts at the boundary, and replays only the suffix;
* 6.7 — a snapshot taken is traced as ``snapshot`` and joins the digest, which
  is a documented digest-visible change: the corpus entry that exercises it
  goes through the generator, is locked in the MANIFEST, and gets a reference
  digest from the tool (``docs/runbooks/regenerate-traces.md``).

A one-voter cluster is used where the rule is about a node and its own log —
it commits its own writes, so compaction has something to compact. The
transfer surface (6.4, 6.5) is declared by the seed and accepted by the
following task, not by this one.
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
from tidewater.log import RaftLog
from tidewater.membership import Configuration
from tidewater.messages import AppendEntries
from tidewater.node import CANDIDATE, LEADER, Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.schedule import Action
from tidewater.statemachine import Command, KVStateMachine
from tidewater.storage import Storage
from tidewater.trace import DIGEST_KINDS, Trace

ALONE = ("n1",)
FIVE = ("n1", "n2", "n3", "n4", "n5")
NEW_SCHEDULE = "compaction-quiet"


def repository() -> Path:
    """The workspace root: where ``tools/`` and ``schedules/`` live."""

    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (base / "tools" / "gen_schedules.py").is_file():
            return base
    raise AssertionError("the repository tools are not reachable from the workspace")


def tool(name, *arguments):
    completed = subprocess.run(
        [sys.executable, str(repository() / "tools" / name), *[str(a) for a in arguments]],
        cwd=str(repository()), capture_output=True, text=True, timeout=300,
    )
    return completed


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


def leader_alone(threshold=5, seed=7):
    """A one-voter cluster: it elects itself and commits what it proposes."""

    node = make_node("n1", voters=ALONE, seed=seed, compaction_threshold=threshold)
    for _ in range(200):
        node.tick(node.global_tick + 1)
        if node.role == LEADER:
            break
    assert node.role == LEADER, node.describe()
    node.drain_outbox()
    return node


def write(node, count):
    for index in range(count):
        node.propose(Command("set", f"k{index}", str(index)))
        node.drain_outbox()
    return node


def quiet_cluster(threshold, ticks=900, seed=21):
    from tidewater.network import NetworkOptions
    from tidewater.schedule import Schedule

    schedule = Schedule(
        name="hidden-quiet-compaction",
        nodes=FIVE,
        seed=seed,
        ticks=ticks,
        actions=[Action(at=1, kind="workload",
                        args={"count": 40, "every": 15, "key_prefix": "q"})],
        node_options=NodeOptions(compaction_threshold=threshold, election_timeout=40, heartbeat_interval=8),
        network_options=NetworkOptions(max_delay=3),
    )
    return Cluster(schedule)


def test_the_record_is_built_at_last_applied_and_made_durable_before_the_log_it_compacts():
    """6.2 — record first, then log; the record is the state machine."""

    node = leader_alone(threshold=4)
    write(node, 6)
    record = node.storage.snapshot
    assert record is not None, "a node past its compaction threshold has a snapshot"

    assert record.last_included_index <= node.state_machine.last_applied
    assert record.last_included_term == node.log.term_at(record.last_included_index)
    assert record.config == ALONE

    durable = node.storage.durable_view()
    assert durable.snapshot is not None, "the record is durable, not merely written"
    assert durable.snapshot.last_included_index == record.last_included_index
    assert durable.snapshot.last_included_term == record.last_included_term

    restored = KVStateMachine.from_snapshot_bytes(record.state)
    assert restored.last_applied == record.last_included_index
    assert restored.digest() == node.state_machine.digest()


def test_the_boundary_term_is_kept_and_the_boundary_never_passes_last_applied():
    """6.3 — ``term_at(base_index) == base_term``, a suffix is kept, and
    nothing applied is compacted away."""

    node = write(leader_alone(threshold=5), 16)
    record = node.storage.snapshot
    assert record is not None

    assert node.log.base_index > 0, "the log was compacted"
    assert node.log.base_index <= record.last_included_index <= node.state_machine.last_applied
    assert node.log.term_at(node.log.base_index) == node.log.base_term
    assert len(node.log) >= 1, "compaction keeps a suffix"
    assert node.state_machine.get("k15") == "15"
    assert node.state_machine.last_applied == node.log.last_index


def test_log_matching_at_the_boundary_behaves_as_for_an_entry():
    """6.3 — an append whose prefix is the boundary is accepted on the boundary
    term; the same index with any other term is refused."""

    node = write(leader_alone(threshold=5), 14)
    boundary = node.log.base_index
    assert boundary > 0

    follower = make_node("n2", voters=("n2",), seed=11)
    follower.log = RaftLog(entries=[], base_index=boundary, base_term=node.log.base_term)
    follower.state_machine.last_applied = boundary
    follower.commit_index = boundary
    follower.storage.set_term(1, None)

    follower.receive("n1", AppendEntries(
        term=1, leader_id="n1", prev_log_index=boundary, prev_log_term=node.log.base_term,
        entries=(), leader_commit=boundary))
    assert follower.trace.last("reject_append") is None, "the boundary term matches the boundary"

    follower.receive("n1", AppendEntries(
        term=1, leader_id="n1", prev_log_index=boundary, prev_log_term=node.log.base_term + 1,
        entries=(), leader_commit=boundary))
    rejected = follower.trace.last("reject_append")
    assert rejected is not None and rejected.fields["reason"] == "log_mismatch"


def test_a_restart_with_a_snapshot_starts_at_the_boundary_and_replays_only_the_suffix():
    """6.6 and 5.4 — the restart is not a replay from index 1."""

    node = write(leader_alone(threshold=5), 16)
    record = node.storage.snapshot
    applied_before = node.state_machine.last_applied
    applies_before = len(node.trace.of_kind("apply"))
    boundary = node.log.base_index

    node.crash()
    node.restart()
    node.drain_outbox()

    assert node.state_machine.get("k0") == "0", "the snapshot carries the prefix"
    assert node.state_machine.last_applied >= boundary, "resumed from the snapshot, not from one"
    assert node.commit_index >= record.last_included_index
    replayed = len(node.trace.of_kind("apply")) - applies_before
    assert replayed == 0, "a restart from a snapshot re-applies nothing"

    # The restarted node stands again and writes: the suffix continues from
    # where the snapshot left the log, not from index 1.
    for _ in range(200):
        node.tick(node.global_tick + 1)
        if node.role == LEADER:
            break
    assert node.role == LEADER, node.describe()
    for index in range(3):
        node.propose(Command("set", f"after{index}", str(index)))
        node.drain_outbox()
    assert node.state_machine.get("after2") == "2"
    assert node.state_machine.get("k15") == "15"
    assert node.state_machine.last_applied > applied_before


def test_a_snapshot_is_traced_and_takes_its_place_in_the_digest():
    """6.7 — ``snapshot`` is committed-visible and is recorded with the
    boundary and what was dropped."""

    assert "snapshot" in DIGEST_KINDS

    node = write(leader_alone(threshold=4), 8)
    events = node.trace.of_kind("snapshot")
    assert events, "taking a snapshot is traced"
    event = events[-1]
    assert event.fields["last_included_index"] > 0
    assert event.fields["last_included_term"] > 0
    assert event.fields["dropped"] >= 1
    assert any(digest_event.kind == "snapshot" for digest_event in node.trace.digest_events())


def test_a_cluster_under_compaction_stays_safe_and_makes_progress():
    """Every node snapshots independently (6.1) while a five-node cluster
    writes: no invariant breaks and the work commits."""

    cluster = quiet_cluster(threshold=16)
    result = cluster.run()
    assert result.ok, result.render()
    assert sum(result.commit_indexes.values()) > 0, "the cluster committed"
    with_snapshot = [node.node_id for node in cluster.nodes.values() if node.storage.snapshot is not None]
    assert len(with_snapshot) >= 3, f"only {with_snapshot} compacted their logs"
    digests = {node.state_machine.digest() for node in cluster.nodes.values()}
    assert len(digests) == 1, "every node applied the same entries"


def test_the_compaction_run_is_reproducible_and_recorded_in_the_corpus():
    """The value this session has to carry: the digest of the new corpus entry,
    produced by the tool that owns it and reproducible run after run."""

    root = repository()
    path = root / "schedules" / f"{NEW_SCHEDULE}.json"
    assert path.is_file(), f"{NEW_SCHEDULE}.json is part of the corpus now"

    from tidewater.schedule import schedule_from_dict

    raw = path.read_text(encoding="utf-8")
    schedule = schedule_from_dict(json.loads(raw))
    first = Cluster(schedule).run()
    assert first.ok, first.render()
    second = Cluster(schedule_from_dict(json.loads(raw))).run()
    assert first.digest == second.digest, "the same schedule runs the same way twice"

    recorded = (root / "traces" / f"{NEW_SCHEDULE}.digest").read_text(encoding="utf-8")
    assert first.digest[:8] != "" and recorded.strip(), "the reference digest exists"


def test_the_new_corpus_entry_is_generated_locked_and_digested_by_the_tools():
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
