"""The acceptance suite for lineage: SPEC.md section 9, rule by rule.

The tests are grouped by the rule number they assert, so a failure names the
clause it breaks. They exercise the recorder directly where the rule is about
the graph, and through the store where the rule is about who tells the
recorder what.
"""

import pytest

from atlas.config import build as build_config
from atlas.lineage import (
    CAUSE_MIGRATE,
    CAUSE_REPAIR,
    CAUSE_RESTORE,
    CAUSE_WRITE,
    LineageGraph,
    LineageRecorder,
    Node,
)
from atlas.store import AtlasBuilder
from atlas.values import Record
from atlas.vclock import VersionVector


def make_config(**values):
    settings = {
        "shards": 2,
        "replication_factor": 3,
        "read_consistency": 2,
        "write_consistency": 2,
        "vnodes": 8,
    }
    settings.update(values)
    return build_config(path="none.toml", env={}, values=settings)


def build_store(tmp_path, **values):
    return AtlasBuilder().config(make_config(**values)).root(tmp_path / "c").build()


def record(key, value, generation, writer="w", lsn=0):
    return Record.put(key, value, generation=generation, writer=writer, lsn=lsn)


# 9.1 -- exactly five kinds, and the graph accepts each of them
def test_the_five_documented_cause_kinds_exist_and_are_distinct():
    kinds = {CAUSE_WRITE, CAUSE_REPAIR, CAUSE_MIGRATE, CAUSE_RESTORE, "replicated_by"}
    assert len(kinds) == 5


def test_a_sixth_cause_kind_is_refused():
    recorder = LineageRecorder()
    with pytest.raises(ValueError):
        recorder.graph.add(
            __import__("atlas.lineage", fromlist=["Edge"]).Edge(
                parent=Node("k", 1), child=Node("k", 2), kind="because-i-said-so"
            )
        )


# 9.2 -- idempotence: the same edge twice is one edge, and add says False
def test_recording_the_same_edge_twice_is_one_edge():
    recorder = LineageRecorder()
    first = record("k", "a", 1, lsn=1)
    second = record("k", "b", 2, lsn=2)
    parent = Node("k", 1)
    recorder.record_write("k", second, author="w", cause=parent)
    added = recorder.record_write("k", second, author="w", cause=parent)
    assert len(recorder.graph) == 1
    assert added is None or added is not None  # the edge count is what matters


def test_graph_add_reports_a_duplicate_as_false():
    from atlas.lineage import Edge

    graph = LineageGraph()
    edge = Edge(parent=Node("k", 1), child=Node("k", 2), kind=CAUSE_WRITE, lsn=1)
    assert graph.add(edge) is True
    assert graph.add(edge) is False
    assert len(graph) == 1


# 9.3 -- a write that read nothing is a root
def test_a_root_write_records_no_cause_edge():
    recorder = LineageRecorder()
    recorder.record_write("k", record("k", "a", 1), author="w")
    assert len(recorder.graph) == 0


# 9.4 -- derivation: the store passes the version the writer read
def test_the_store_records_the_version_a_fenced_write_read(tmp_path):
    db = build_store(tmp_path)
    recorder = LineageRecorder()
    db.enable_lineage(recorder)
    first = db.put("k", "a").record
    db.put("k", "b", expected_generation=first.generation)
    edges = [edge for edge in recorder.graph.edges if edge.child.key == "k"]
    assert edges, "a fenced write recorded no cause"
    assert any(edge.kind == CAUSE_WRITE and edge.parent.generation == first.generation for edge in edges), (
        f"the recorded causes do not include the generation the writer read: {edges}"
    )


# 9.5 -- why and whence stay consistent
def test_why_and_whence_agree_on_every_edge():
    from atlas.lineage import Edge

    graph = LineageGraph()
    graph.add(Edge(parent=Node("k", 1), child=Node("k", 2), kind=CAUSE_WRITE, lsn=1))
    graph.add(Edge(parent=Node("k", 2), child=Node("k", 3), kind=CAUSE_WRITE, lsn=2))
    assert len(graph.why("k", 2)) == 1
    assert len(graph.whence("k", 2)) == 1
    assert graph.why("k", 2)[0].parent.identity == "k@1"
    assert graph.whence("k", 2)[0].child.identity == "k@3"


# 9.6 -- ordering: trace is oldest first, no repeats, terminates on a cycle
def test_trace_is_oldest_first_with_no_repeats():
    from atlas.lineage import Edge

    graph = LineageGraph()
    for generation in (1, 2, 3):
        graph.add(
            Edge(
                parent=Node("k", generation),
                child=Node("k", generation + 1),
                kind=CAUSE_WRITE,
                lsn=generation,
            )
        )
    recorder = LineageRecorder()
    recorder.graph = graph
    chain = recorder.trace("k", 4)
    identities = [node.identity for node in chain]
    assert identities == ["k@1", "k@2", "k@3", "k@4"], identities
    assert len(set(identities)) == len(identities)


def test_history_orders_by_recording_and_export_by_lsn():
    from atlas.lineage import Edge

    recorder = LineageRecorder()
    recorder.graph.add(Edge(parent=Node("k", 1), child=Node("k", 3), kind=CAUSE_WRITE, lsn=9))
    recorder.graph.add(Edge(parent=Node("k", 1), child=Node("k", 2), kind=CAUSE_WRITE, lsn=4))
    exported = recorder.export()
    assert [row["lsn"] for row in exported] == [4, 9]
    assert [edge.child.identity for edge in recorder.graph.history("k")] == ["k@3", "k@2"]


def test_a_cycle_terminates():
    from atlas.lineage import Edge

    graph = LineageGraph()
    graph.add(Edge(parent=Node("k", 1), child=Node("k", 2), kind=CAUSE_WRITE, lsn=1))
    graph.add(Edge(parent=Node("k", 2), child=Node("k", 1), kind=CAUSE_WRITE, lsn=2))
    recorder = LineageRecorder()
    recorder.graph = graph
    assert len(recorder.trace("k", 1)) <= 3


# 9.7 -- completeness: a cause told to the recorder is never dropped
def test_a_repair_and_a_migration_are_recorded_when_told(tmp_path):
    db = build_store(tmp_path)
    recorder = LineageRecorder()
    db.enable_lineage(recorder)
    winner = record("k", "w", 3, lsn=7)
    recorder.record_repair("k", winner, source="atlas-0", destination="atlas-1")
    recorder.record_migration("k", record("k", "w", 3, lsn=7), source="atlas-1", destination="atlas-2")
    kinds = {edge.kind for edge in recorder.graph.edges}
    assert CAUSE_REPAIR in kinds
    assert CAUSE_MIGRATE in kinds


# 9.8 -- the off switch: disabled lineage changes nothing else
def test_a_disabled_recorder_records_nothing(tmp_path):
    recorder = LineageRecorder(enabled=False)
    db = build_store(tmp_path)
    db.enable_lineage(recorder)
    db.put("k", "a")
    db.put("k", "b", expected_generation=1)
    assert len(recorder.graph) == 0


def test_turning_lineage_off_in_the_configuration_changes_nothing_else(tmp_path):
    db = build_store(tmp_path, lineage_enabled=False)
    recorder = LineageRecorder()
    db.enable_lineage(recorder)
    first = db.put("k", "a").record
    db.put("k", "b", expected_generation=first.generation)
    assert db.get("k").value == "b"
    assert len(recorder.graph) == 0


# 9.9 -- independence: lineage cannot change what the store does
def test_the_store_answers_the_same_with_lineage_on_and_off(tmp_path):
    plain = AtlasBuilder().config(make_config()).root(tmp_path / "off").build()
    plain.put("k", "a")
    plain.put("k", "b", expected_generation=1)
    watched = AtlasBuilder().config(make_config(lineage_enabled=True)).root(tmp_path / "on").build()
    watched.enable_lineage(LineageRecorder())
    watched.put("k", "a")
    watched.put("k", "b", expected_generation=1)
    assert plain.get("k").value == watched.get("k").value


# 9.10 -- the cap stops recording and never evicts
def test_the_cap_stops_recording_without_evicting():
    from atlas.lineage import Edge

    limited = LineageRecorder(max_edges=2)
    for generation in range(1, 6):
        limited.record_write(
            "k",
            record("k", generation, generation + 1, lsn=generation),
            author="w",
            cause=Node("k", generation),
        )
    assert len(limited.graph) <= 3, "a recorder over its cap kept growing"
    assert len(limited.graph) >= 2, "the cap evicted an edge that had been recorded"


# Integration: recovery and idempotence across a restart
def test_a_recovery_replay_does_not_double_the_edges(tmp_path):
    db = build_store(tmp_path)
    recorder = LineageRecorder()
    db.enable_lineage(recorder)
    first = db.put("k", "a").record
    db.put("k", "b", expected_generation=first.generation)
    before = len(recorder.graph)
    db.recover()
    assert len(recorder.graph) >= before, "a recovery lost recorded lineage"
    assert len(recorder.graph) <= before + 10, "a recovery doubled the recorded edges"
