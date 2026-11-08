"""Visible checks for the lineage contract. A subset, not the whole evidence."""

import pytest

from atlas.config import build as build_config
from atlas.lineage import CAUSE_WRITE, LineageGraph, LineageRecorder, Node
from atlas.store import AtlasBuilder
from atlas.values import Record


def build(tmp_path, **values):
    settings = {
        "shards": 2,
        "replication_factor": 3,
        "read_consistency": 2,
        "write_consistency": 2,
        "vnodes": 8,
    }
    settings.update(values)
    config = build_config(path="none.toml", env={}, values=settings)
    return AtlasBuilder().config(config).root(tmp_path / "c").build()


def test_an_edge_is_its_endpoints_and_its_kind():
    from atlas.lineage import Edge

    graph = LineageGraph()
    edge = Edge(parent=Node("k", 1), child=Node("k", 2), kind=CAUSE_WRITE, lsn=1)
    assert graph.add(edge) is True
    assert graph.add(edge) is False
    assert len(graph) == 1


def test_a_write_that_read_a_generation_records_a_cause(tmp_path):
    db = build(tmp_path)
    recorder = LineageRecorder()
    db.enable_lineage(recorder)
    first = db.put("k", "a").record
    db.put("k", "b", expected_generation=first.generation)
    assert any(edge.kind == CAUSE_WRITE for edge in recorder.graph.edges)


def test_a_root_write_records_no_cause():
    recorder = LineageRecorder()
    recorder.record_write("k", Record.put("k", "a", generation=1), author="w")
    assert len(recorder.graph) == 0


def test_a_disabled_recorder_records_nothing(tmp_path):
    db = build(tmp_path)
    recorder = LineageRecorder(enabled=False)
    db.enable_lineage(recorder)
    first = db.put("k", "a").record
    db.put("k", "b", expected_generation=first.generation)
    assert len(recorder.graph) == 0
    assert db.get("k").value == "b"


def test_trace_is_oldest_first():
    from atlas.lineage import Edge

    recorder = LineageRecorder()
    for generation in (1, 2, 3):
        recorder.graph.add(
            Edge(
                parent=Node("k", generation),
                child=Node("k", generation + 1),
                kind=CAUSE_WRITE,
                lsn=generation,
            )
        )
    assert [node.identity for node in recorder.trace("k", 4)] == ["k@1", "k@2", "k@3", "k@4"]
