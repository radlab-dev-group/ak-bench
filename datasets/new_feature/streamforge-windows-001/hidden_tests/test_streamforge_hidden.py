"""Cross-module contracts and an independent event-list oracle."""

import json
import os
import random
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, replace

import pytest
from streamforge import Change, Event, Pipeline, Processor, Result, Window
from streamforge.checkpoint import save
from streamforge.errors import IdentityConflict, InvalidCheckpoint, OffsetConflict


def event(offset, timestamp, value=1, *, partition="a", key="key", event_id=None):
    return Event(partition, offset, event_id or f"{partition}:{offset}", key, timestamp, value)


def pipeline(*windows, partitions=("a",), lateness=30):
    return Pipeline(partitions, tuple(windows) or (Window("fixed", "fixed", size=10),), lateness)


def signature(changes):
    return [asdict(change) for change in changes]


class BatchOracle:
    """Recompute from raw unique events; use no production operator helpers."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.progress = dict.fromkeys(configuration.partitions)
        self.idle = set()
        self.watermark = None
        self.events = []
        self.identities = set()
        self.late = []
        self.previous = {}
        self.retired = set()
        self.sequence = 0

    def ingest(self, item):
        if item.event_id not in self.identities:
            self.identities.add(item.event_id)
            if self.watermark is not None and (
                item.timestamp + self.configuration.lateness < self.watermark
            ):
                self.late.append((item, self.watermark))
            else:
                self.events.append(item)
        return self.flush()

    def advance(self, partition, value):
        self.progress[partition] = value
        self.refresh()
        return self.flush()

    def mark_idle(self, partition, idle=True):
        if idle:
            self.idle.add(partition)
        else:
            self.idle.discard(partition)
        self.refresh()
        return self.flush()

    def refresh(self):
        active = [value for name, value in self.progress.items() if name not in self.idle]
        if active and all(value is not None for value in active):
            candidate = min(active)
            self.watermark = candidate if self.watermark is None else max(candidate, self.watermark)

    def groups(self):
        groups = []
        by_key = defaultdict(list)
        for item in self.events:
            by_key[item.key].append(item)
        for window in self.configuration.windows:
            for key, items in by_key.items():
                ordered = sorted(items, key=lambda item: (item.timestamp, item.event_id))
                if window.kind == "session":
                    runs = []
                    for item in ordered:
                        if not runs or item.timestamp > runs[-1][1]:
                            runs.append([item.timestamp, item.timestamp + window.gap, [item]])
                        else:
                            runs[-1][1] = max(runs[-1][1], item.timestamp + window.gap)
                            runs[-1][2].append(item)
                    groups.extend((window.name, key, *run) for run in runs)
                else:
                    stride = window.size if window.kind == "fixed" else window.step
                    lowest = (ordered[0].timestamp - window.size) // stride * stride
                    highest = ordered[-1].timestamp // stride * stride
                    for start in range(lowest, highest + 1, stride):
                        members = [
                            item for item in items if start <= item.timestamp < start + window.size
                        ]
                        if members:
                            groups.append((window.name, key, start, start + window.size, members))
        return groups

    def flush(self):
        current = {}
        retiring = set()
        for window, key, start, end, members in self.groups():
            address = window, key, start, end
            if address in self.retired or self.watermark is None or end > self.watermark:
                continue
            values = [item.value for item in members]
            current[address] = Result(
                window, key, start, end, len(values), sum(values), min(values), max(values)
            )
            if self.watermark > end + self.configuration.lateness:
                retiring.add(address)
        changes = []
        for operation, source, other in (
            ("retract", self.previous, current),
            ("upsert", current, self.previous),
        ):
            for address, result in sorted(source.items()):
                if other.get(address) != result:
                    self.sequence += 1
                    changes.append(Change(self.sequence, operation, result))
        self.previous = {
            address: result for address, result in current.items() if address not in retiring
        }
        self.retired.update(retiring)
        return changes


@pytest.mark.parametrize("timestamp,start", [(-21, -30), (-10, -10), (-1, -10), (0, 0), (10, 10)])
def test_fixed_floor_boundaries(timestamp, start):
    processor = Processor(pipeline())
    processor.ingest(event(0, timestamp, -7))
    (change,) = processor.advance("a", start + 10)
    assert change.result == Result("fixed", "key", start, start + 10, 1, -7, -7, -7)


@pytest.mark.parametrize("timestamp", [-17, -7, -1, 0, 4, 7, 13])
def test_sliding_half_open_nondivisible_size(timestamp):
    processor = Processor(pipeline(Window("slide", "sliding", size=11, step=4)))
    processor.ingest(event(0, timestamp, 3))
    changes = processor.advance("a", timestamp + 20)
    starts = [start for start in range(-40, 41, 4) if start <= timestamp < start + 11]
    assert [change.result.start for change in changes] == starts
    assert all(change.result.total == 3 for change in changes)


def test_all_retractions_precede_any_upserts_across_keys_and_windows():
    processor = Processor(
        pipeline(Window("z", "fixed", size=10), Window("a", "sliding", size=10, step=5))
    )
    processor.ingest(event(0, 1, key="z"))
    processor.ingest(event(1, 2, key="a"))
    processor.advance("a", 10)
    changes = processor.ingest(event(2, 3, 9, key="a"))
    operations = [change.operation for change in changes]
    assert operations == ["retract"] * 3 + ["upsert"] * 3
    for operation in ("retract", "upsert"):
        addresses = [change.result.address for change in changes if change.operation == operation]
        assert addresses == sorted(addresses)


def test_bridge_retracts_closed_sessions_and_reopens_merged_session():
    processor = Processor(pipeline(Window("s", "session", gap=5), lateness=100))
    processor.ingest(event(0, 0, 2))
    processor.ingest(event(1, 10, 7))
    original = processor.advance("a", 15)
    assert len(original) == 2
    processor.ingest(event(2, 18, 11))
    changes = processor.ingest(event(3, 5, 3))
    assert [(change.operation, change.result.start, change.result.end) for change in changes] == [
        ("retract", 0, 5),
        ("retract", 10, 15),
        ("upsert", 0, 15),
    ]
    changes = processor.ingest(event(4, 14, -4))
    assert [(change.operation, change.result.start, change.result.end) for change in changes] == [
        ("retract", 0, 15)
    ]
    (final,) = processor.advance("a", 23)
    assert final.result == Result("s", "key", 0, 23, 5, 19, -4, 11)


def test_transitive_merge_is_independent_of_delivery_order():
    configuration = pipeline(Window("s", "session", gap=4))
    results = []
    for order in ([0, 8, 16, 4, 12], [12, 4, 16, 8, 0]):
        processor = Processor(configuration)
        for offset, timestamp in enumerate(order):
            processor.ingest(event(offset, timestamp, timestamp))
        results.append(processor.advance("a", 20))
    assert results[0] == results[1]
    assert results[0][0].result.count == 5


def test_session_keys_and_window_names_are_independent():
    configuration = pipeline(Window("short", "session", gap=3), Window("long", "session", gap=9))
    processor, oracle = Processor(configuration), BatchOracle(configuration)
    for offset, (timestamp, key) in enumerate([(0, "a"), (4, "b"), (7, "a"), (9, "a")]):
        item = event(offset, timestamp, offset - 2, key=key)
        assert processor.ingest(item) == oracle.ingest(item)
    assert processor.advance("a", 50) == oracle.advance("a", 50)


def test_global_watermark_idleness_reactivation_and_no_implicit_progress():
    processor = Processor(pipeline(partitions=("a", "b")))
    processor.ingest(event(0, 1))
    assert processor.advance("a", 10) == []
    assert processor.watermark is None
    assert len(processor.mark_idle("b")) == 1
    assert processor.mark_idle("a") == []
    assert processor.watermark == 10
    processor.mark_idle("b", False)
    processor.advance("b", 2)
    assert processor.watermark == 10
    processor.ingest(event(0, 500, partition="b"))
    assert processor.watermark == 10
    processor.advance("b", 20)
    assert processor.watermark == 20


def test_lateness_equality_and_global_identity_deduplication():
    processor = Processor(pipeline(partitions=("a", "b"), lateness=5))
    processor.advance("a", 10)
    processor.advance("b", 10)
    processor.ingest(event(0, 5, 8, event_id="equal"))
    processor.ingest(event(1, 4, 99, event_id="late"))
    processor.ingest(event(0, 4, 99, partition="b", event_id="late"))
    processor.ingest(event(1, 5, 8, partition="b", event_id="equal"))
    assert len(processor.late) == 1
    assert processor.late[0].watermark == 10
    assert processor.offsets == {"a": 1, "b": 1}
    assert processor.advance("a", 15) == []
    assert processor.advance("b", 15) == []


def test_offset_conflict_precedes_identity_conflict_and_is_atomic(tmp_path):
    processor = Processor(pipeline())
    first = event(0, 1, event_id="stable")
    processor.ingest(first)
    processor.advance("a", 10)
    path = tmp_path / "before.json"
    processor.checkpoint(path)
    before = path.read_bytes()
    with pytest.raises(OffsetConflict):
        processor.ingest(replace(first, value=99))
    with pytest.raises(OffsetConflict):
        processor.ingest(replace(first, offset=2, value=99))
    with pytest.raises(IdentityConflict):
        processor.ingest(replace(first, offset=1, value=99))
    with pytest.raises(ValueError):
        processor.advance("a", 9)
    with pytest.raises(ValueError):
        processor.mark_idle("unknown")
    processor.checkpoint(path)
    assert path.read_bytes() == before
    assert processor.ingest(first) == []
    changes = processor.ingest(event(1, 2, 4))
    assert changes[-1].result.count == 2


def test_finalization_is_strict_and_does_not_retract(tmp_path):
    processor = Processor(pipeline(lateness=5))
    processor.ingest(event(0, 9, 3))
    assert len(processor.advance("a", 10)) == 1
    assert processor.advance("a", 15) == []
    assert processor.index.ready(15)
    assert processor.advance("a", 16) == []
    assert processor.index.ready(16) == []
    path = tmp_path / "empty.json"
    processor.checkpoint(path)
    restored = Processor.restore(processor.pipeline, path)
    assert restored.ingest(event(0, 9, 3)) == []
    assert restored.advance("a", 100) == []


def test_large_watermark_jump_emits_once_then_finalizes():
    processor = Processor(pipeline(lateness=0))
    processor.ingest(event(0, 1))
    changes = processor.advance("a", 1000)
    assert [change.operation for change in changes] == ["upsert"]
    assert processor.index.ready(1000) == []
    assert processor.advance("a", 2000) == []


def test_checkpoint_reordered_configuration_and_snapshot_independence(tmp_path):
    configuration = pipeline(
        Window("s", "session", gap=5), Window("f", "fixed", size=10), partitions=("a", "b")
    )
    processor = Processor(configuration)
    processor.ingest(event(0, 1))
    processor.advance("a", 10)
    processor.mark_idle("b")
    path = tmp_path / "saved.json"
    processor.checkpoint(path)
    original = path.read_bytes()
    equivalent = Pipeline(
        ("b", "a"), tuple(reversed(configuration.windows)), configuration.lateness
    )
    restored = Processor.restore(equivalent, path)
    restored.checkpoint(tmp_path / "same.json")
    assert (tmp_path / "same.json").read_bytes() == original
    expected = processor.ingest(event(1, 2, 8))
    assert path.read_bytes() == original
    assert restored.ingest(event(1, 2, 8)) == expected
    assert processor.ingest(event(2, 2, 8, event_id="a:1")) == []


def test_checkpoint_corruption_and_incompatible_configuration(tmp_path):
    configuration = pipeline()
    path = tmp_path / "state.json"
    Processor(configuration).checkpoint(path)
    with pytest.raises(InvalidCheckpoint):
        Processor.restore(pipeline(lateness=31), path)
    envelope = json.loads(path.read_bytes())
    envelope["sha256"] = "0" * 64
    path.write_text(json.dumps(envelope))
    with pytest.raises(InvalidCheckpoint):
        Processor.restore(configuration, path)
    save(path, configuration.fingerprint, {})
    with pytest.raises(InvalidCheckpoint):
        Processor.restore(configuration, path)


def test_restore_in_fresh_interpreter_preserves_sequence_and_dedup(tmp_path):
    configuration = pipeline(lateness=30)
    processor = Processor(configuration)
    processor.ingest(event(0, 1, 4))
    processor.advance("a", 10)
    path = tmp_path / "state.json"
    processor.checkpoint(path)
    script = """
import json, sys
from pathlib import Path
from dataclasses import asdict
from streamforge import Pipeline, Window, Processor, Event
configuration = Pipeline(('a',), (Window('fixed', 'fixed', size=10),), 30)
processor = Processor.restore(configuration, Path(sys.argv[1]))
assert processor.ingest(Event('a', 0, 'a:0', 'key', 1, 4)) == []
changes = processor.ingest(Event('a', 1, 'a:1', 'key', 2, 8))
print(json.dumps([asdict(item) for item in changes], sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=20,
        check=True,
    )
    assert json.loads(completed.stdout) == signature(processor.ingest(event(1, 2, 8)))


@pytest.mark.parametrize("seed", range(24))
def test_generated_traces_match_independent_batch_model_and_restart(seed, tmp_path):
    randomizer = random.Random(seed)
    configuration = pipeline(
        Window("fixed", "fixed", size=11),
        Window("sliding", "sliding", size=13, step=5),
        Window("session", "session", gap=7),
        partitions=("a", "b", "c"),
        lateness=19,
    )
    processor, oracle = Processor(configuration), BatchOracle(configuration)
    offsets = dict.fromkeys(configuration.partitions, -1)
    progress = dict.fromkeys(configuration.partitions, -30)
    delivered = []
    for step in range(90):
        partition = randomizer.choice(configuration.partitions)
        choice = randomizer.randrange(10)
        if choice < 6:
            offsets[partition] += 1
            timestamp = randomizer.randint(-30, 65)
            item = event(
                offsets[partition],
                timestamp,
                randomizer.randint(-20, 20),
                partition=partition,
                key=randomizer.choice(["alpha", "beta", "gamma"]),
            )
            if delivered and choice == 0:
                original = randomizer.choice(delivered)
                item = replace(original, partition=partition, offset=offsets[partition])
            delivered.append(item)
            assert processor.ingest(item) == oracle.ingest(item), (seed, step, item)
        elif choice < 9:
            progress[partition] += randomizer.randint(0, 12)
            assert processor.advance(partition, progress[partition]) == oracle.advance(
                partition, progress[partition]
            )
        else:
            idle = partition not in oracle.idle
            assert processor.mark_idle(partition, idle) == oracle.mark_idle(partition, idle)
        assert processor.watermark == oracle.watermark
        assert [(item.event, item.watermark) for item in processor.late] == oracle.late
        if step % 11 == 0:
            path = tmp_path / "resume.json"
            processor.checkpoint(path)
            processor = Processor.restore(configuration, path)
    for partition in configuration.partitions:
        assert processor.mark_idle(partition, False) == oracle.mark_idle(partition, False)
        assert processor.advance(partition, 1000) == oracle.advance(partition, 1000)
    assert processor.index.ready(1000) == []
