"""The acceptance suite for schema evolution: SPEC.md section 10, rule by rule.

The tests are grouped by the rule they assert, so a failure names the clause
it breaks. Rows are read from large legacy fixtures under ``fixtures/`` (a v1
write-ahead log of three segments with a torn tail, and a v2 snapshot); their
expected digests are in ``fixtures/expected.json``. The procedure half of the
contract — the generated tables, the lock and the goldens — is checked by
running the repository's own tools from the workspace root.
"""

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from atlas import evolution, tables
from atlas.codec import FrameKind, canonical, decode, encode, iter_frames
from atlas.errors import AtlasError
from atlas.registry import STRATEGIES, StrategySet
from atlas.storage import ShardStorage
from atlas.values import Record
from atlas.vclock import VersionVector
from atlas.wal import WriteAheadLog

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
WORKSPACE = pathlib.Path.cwd()

LAYOUTS = {
    1: ("key", "value", "gen", "lsn"),
    2: ("key", "value", "gen", "lsn", "at", "writer"),
    3: ("key", "value", "gen", "vec", "deleted", "lsn", "at", "writer", "attrs"),
}
STEP_NAMES = {"records:v1->v2", "records:v2->v3", "records:v3->v2", "records:v2->v1"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_of(records) -> str:
    return sha256(b"".join(canonical(evolution.encode_row(record)) for record in records))


def tool(*arguments):
    return subprocess.run(
        [sys.executable, str(WORKSPACE / "tools" / arguments[0]), *arguments[1:]],
        cwd=str(WORKSPACE),
        env={"PYTHONPATH": str(WORKSPACE / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def legacy_log(tmp_path):
    target = tmp_path / "v1-wal"
    shutil.copytree(FIXTURES / "v1-wal", target)
    return target


@pytest.fixture
def storage(tmp_path):
    return ShardStorage(tmp_path / "shard", 0, repair_on_open=True)


# --------------------------------------------------------------- 10.2 layouts
def test_10_2_layouts_are_declared_in_the_schema_and_generated_into_the_tables():
    assert getattr(tables, "LAYOUTS", None) == LAYOUTS
    assert evolution.layouts() == LAYOUTS
    assert evolution.CURRENT_VERSION == tables.SCHEMA_VERSION == 3
    document = json.loads((WORKSPACE / "schema" / "tables.json").read_text(encoding="utf-8"))
    declared = {int(str(k).lstrip("v")): tuple(v["fields"] if isinstance(v, dict) else v) for k, v in document["layouts"].items()}
    assert declared == LAYOUTS


def test_10_3_detection_is_total_and_picks_the_highest_fitting_layout():
    assert evolution.detect_version({"key": "k", "value": "1", "gen": 1, "lsn": 1}) == 1
    assert evolution.detect_version({"key": "k", "value": 1, "gen": 1, "lsn": 1, "at": 0, "writer": "w"}) == 2
    current = evolution.encode_row(Record.put("k", 1, written_at=0))
    assert evolution.detect_version(current) == 3
    assert evolution.detect_version({"v": 2, "key": "k", "value": 1, "gen": 1, "lsn": 1, "at": 0, "writer": "w"}) == 2
    with pytest.raises(evolution.UnknownLayoutError):
        evolution.detect_version({"key": "k"})
    with pytest.raises(evolution.UnknownLayoutError):
        evolution.upgrade({"key": "k", "value": "1", "gen": 1, "lsn": 1}, to=9)
    assert issubclass(evolution.UnknownLayoutError, AtlasError)


# ---------------------------------------------------------- 10.4 on-read upgrade
def test_10_4_a_legacy_v1_log_is_upgraded_on_read_and_never_rewritten(legacy_log):
    before = {path.name: sha256(path.read_bytes()) for path in legacy_log.iterdir()}
    records = evolution.read_log(legacy_log)
    after = {path.name: sha256(path.read_bytes()) for path in legacy_log.iterdir()}
    assert after == before, "on-read upgrade must not rewrite the log"
    assert len(records) == EXPECTED["v1_wal_records"]
    assert digest_of(records) == EXPECTED["v1_upgraded_sha256"]
    latest = {}
    for record in records:
        latest[record.key] = record
    live = sorted(key for key, record in latest.items() if not record.deleted)
    tombstones = sorted(key for key, record in latest.items() if record.deleted)
    assert len(live) == EXPECTED["v1_live_keys"]
    assert len(tombstones) == EXPECTED["v1_tombstone_keys"]
    assert live[0] == EXPECTED["v1_first_live_key"]
    assert tombstones[-1] == EXPECTED["v1_last_tombstone_key"]
    for record in records[:50]:
        assert record.writer == evolution.LEGACY_WRITER
        assert dict(record.vector.counters) == {evolution.LEGACY_WRITER: record.generation}
        assert record.written_at == 0
        assert record.attributes == ()
        assert not isinstance(record.value, str) or record.value == json.loads(json.dumps(record.value))


def test_10_4_a_v1_value_is_text_and_comes_back_as_json():
    payload = {"key": "k", "value": '{"a":[1,2.5],"b":"é"}', "gen": 2, "lsn": 7}
    record = evolution.decode_row(payload)
    assert record.value == {"a": [1, 2.5], "b": "é"}
    assert record.generation == 2 and record.lsn == 7
    assert not record.deleted
    tomb = evolution.decode_row({"key": "k", "value": None, "gen": 3, "lsn": 8})
    assert tomb.deleted and tomb.value is None


def test_10_4_a_v2_snapshot_is_upgraded_on_read():
    records = evolution.read_snapshot(FIXTURES / "v2-snapshot-000000006200.snap")
    assert len(records) == EXPECTED["v2_snapshot_records"]
    assert sum(1 for record in records if record.deleted) == EXPECTED["v2_tombstones"]
    assert digest_of(records) == EXPECTED["v2_upgraded_sha256"]
    for record in records[:100]:
        assert record.writer in {"n1", "n2", "n3", "n4"}
        assert dict(record.vector.counters) == {record.writer: record.generation}
        assert record.written_at > 0


def test_10_4_the_log_reader_stops_at_the_torn_tail(legacy_log):
    last = sorted(legacy_log.iterdir())[-1]
    frames = list(WriteAheadLog(legacy_log, repair_on_open=False).scan(last))
    assert frames[-1][0] is None, "the fixture carries a torn frame at its tail"
    records = evolution.read_log(legacy_log)
    assert all(record.key != "torn:0000" for record in records)


# ------------------------------------------------------------- 10.5 dual-write
def test_10_5_a_window_makes_writes_visible_to_a_pinned_reader(storage):
    plain = storage.put("plain", {"n": 1}, writer="n1")
    window = evolution.MigrationWindow(storage, pinned=1)
    shadowed = window.put("shadowed", {"n": 2, "list": [1, 2]}, writer="n1")
    window.put("gone", "x", writer="n1")
    window.delete("gone", writer="n1")
    assert window.close() == 3
    reader = evolution.PinnedReader(1)
    visible = reader.visible_rows(storage.log)
    assert "plain" not in visible, "a current-layout frame is invisible to a v1 reader"
    assert visible["shadowed"] == {"key": "shadowed", "value": '{"list":[1,2],"n":2}', "gen": 1, "lsn": shadowed.lsn}
    assert visible["gone"]["value"] is None and visible["gone"]["gen"] == 2
    # the current reader is untouched: same records, same recovery
    assert storage.get("plain") == plain
    assert storage.get("shadowed") == shadowed
    assert storage.get("gone") is None
    reopened = storage.reopen()
    assert reopened.get("shadowed") == shadowed
    assert reopened.get("plain") == plain
    assert reopened.get("gone") is None
    assert reopened.recovery.replayed == 4
    with pytest.raises(evolution.EvolutionError):
        window.put("late", 1)


def test_10_5_a_window_pins_an_older_layout_only(storage):
    with pytest.raises(evolution.EvolutionError):
        evolution.MigrationWindow(storage, pinned=3)
    with pytest.raises(evolution.UnknownLayoutError):
        evolution.MigrationWindow(storage, pinned=7)


def test_10_5_shadow_frames_are_control_frames_in_their_own_committed_transaction(storage):
    window = evolution.MigrationWindow(storage, pinned=2)
    record = window.put("k", {"a": 1}, writer="n2")
    kinds = [frame.kind for _path, frame in storage.log.frames()]
    assert kinds == [FrameKind.BEGIN, FrameKind.PUT, FrameKind.COMMIT, FrameKind.BEGIN, FrameKind.CONTROL, FrameKind.COMMIT]
    control = [frame for _path, frame in storage.log.frames() if frame.kind is FrameKind.CONTROL][0]
    assert control.payload == evolution.shadow_payload(record, pinned=2)
    assert control.payload["row"] == {"key": "k", "value": {"a": 1}, "gen": 1, "lsn": record.lsn, "at": record.written_at, "writer": "n2"}
    assert evolution.PinnedReader(2).visible_rows(storage.log)["k"] == control.payload["row"]
    assert evolution.PinnedReader(1).visible_rows(storage.log) == {}


# -------------------------------------------------------------- 10.6 downgrade
def test_10_6_downgrade_equals_what_a_legacy_writer_wrote():
    rows = evolution.golden_rows(WORKSPACE / "schema" / "goldens" / "rows.json")
    goldens = json.loads((WORKSPACE / "schema" / "goldens" / "GOLDENS.json").read_text(encoding="utf-8"))
    for version in (1, 2, 3):
        frames = b"".join(evolution.frame_for(row, version=version) for row in rows)
        assert sha256(frames) == goldens[f"records-v{version}"], f"records-v{version}"
        assert sha256(frames) == sha256((WORKSPACE / "schema" / "goldens" / f"records-v{version}.frame").read_bytes())
    v1 = evolution.encode_row(rows[0], version=1)
    assert set(v1) == set(LAYOUTS[1])
    assert v1["value"] == '{"balance":1250,"currency":"EUR","flags":["verified"]}'
    v2 = evolution.encode_row(rows[2], version=2)
    assert set(v2) == set(LAYOUTS[2]) and v2["value"] is None


def test_10_6_a_pinned_reader_is_served_downgraded_rows():
    record = Record.put("k", {"b": 2, "a": [1, 2.5, "é"]}, generation=4, writer="n1", lsn=9, written_at=1700000000000, attributes={"x": "y"})
    reader = evolution.PinnedReader(1)
    assert reader.read(evolution.encode_row(record)) == {"key": "k", "value": '{"a":[1,2.5,"é"],"b":2}', "gen": 4, "lsn": 9}
    assert evolution.PinnedReader(2).read(evolution.encode_row(record)) == {"key": "k", "value": {"b": 2, "a": [1, 2.5, "é"]}, "gen": 4, "lsn": 9, "at": 1700000000000, "writer": "n1"}
    with pytest.raises(evolution.UnknownLayoutError):
        evolution.PinnedReader(4)


# ------------------------------------------------------------ 10.7 round trip
def test_10_7_every_legacy_frame_survives_the_trip_up_and_down_byte_for_byte(legacy_log):
    first = sorted(legacy_log.iterdir())[0].read_bytes()
    assert sha256(first) == EXPECTED["v1_first_segment_sha256"]
    checked = 0
    for frame in iter_frames(first):
        if frame.kind not in (FrameKind.PUT, FrameKind.DELETE):
            continue
        raw = first[frame.offset : frame.offset + frame.size]
        record = evolution.verify_round_trip(raw)
        assert record.key == frame.payload["key"]
        checked += 1
    assert checked > 500
    snapshot = json.loads((FIXTURES / "v2-snapshot-000000006200.snap").read_text(encoding="utf-8"))
    for item in snapshot["records"][:300]:
        evolution.verify_round_trip(encode(FrameKind.PUT, item))


def test_10_7_the_mismatch_signature_is_stable():
    error = evolution.CodecMismatchError("records-v1", "a" * 64, "b" * 64)
    assert str(error) == f"CodecMismatch(records-v1, expected={'a' * 64}, actual={'b' * 64})"
    assert error.code == "codec_mismatch"
    assert isinstance(error, AtlasError)
    # a frame whose value text is not canonical cannot come back identical,
    # and the error says so with the layout's name, not with a traceback
    frame = encode(FrameKind.PUT, {"key": "k", "value": '{"b": 1, "a": 2}', "gen": 1, "lsn": 1})
    with pytest.raises(evolution.CodecMismatchError) as caught:
        evolution.verify_round_trip(frame)
    assert str(caught.value).startswith("CodecMismatch(records-v1, expected=")


# -------------------------------------------------------------- 10.8 registry
def test_10_8_every_step_is_registered_once_and_drives_the_upgrade():
    fresh = StrategySet()
    evolution.install_upgraders(fresh)
    assert fresh.evolution.names() == frozenset(STEP_NAMES)
    evolution.install_upgraders(fresh)
    assert fresh.evolution.names() == frozenset(STEP_NAMES)
    step = fresh.evolution.resolve("records:v1->v2")
    assert step({"key": "k", "value": "[1]", "gen": 1, "lsn": 1}) == {"key": "k", "value": [1], "gen": 1, "lsn": 1, "at": 0, "writer": "legacy"}
    evolution.install_upgraders(STRATEGIES)
    assert STEP_NAMES <= set(STRATEGIES.evolution.names())
    # a registered step is what the chain uses
    custom = StrategySet()
    evolution.install_upgraders(custom)
    marked = StrategySet()
    marked.evolution.register("records:v1->v2", lambda: (lambda payload: {**step(payload), "writer": "marked"}))
    upgraded = evolution.upgrade({"key": "k", "value": "1", "gen": 1, "lsn": 1}, strategies=marked)
    assert upgraded["writer"] == "marked" and upgraded["vec"] == {"marked": 1}


# ------------------------------------------------------------ 10.9 procedure
def test_10_9_the_tables_are_the_generator_output_and_the_manifest_is_locked():
    generated = tool("gen_tables.py", "--stdout")
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert generated.stdout == (WORKSPACE / "src" / "atlas" / "tables.py").read_text(encoding="utf-8")
    manifest_path = WORKSPACE / "schema" / "MANIFEST"
    assert manifest_path.exists(), "schema/MANIFEST is missing: the tables were not locked"
    manifest = dict(
        line.split("=", 1)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert manifest["schema_version"] == "3"
    assert manifest["tables_json_sha256"] == sha256((WORKSPACE / "schema" / "tables.json").read_bytes())
    assert manifest["tables_py_sha256"] == sha256((WORKSPACE / "src" / "atlas" / "tables.py").read_bytes())
    checked = tool("gen_tables.py", "--check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "locked" in checked.stdout


def test_10_9_the_goldens_verify_with_the_repository_tool():
    verified = tool("verify_goldens.py", "--family", "records")
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "OK records-v1" in verified.stdout
    assert "OK records-v2" in verified.stdout
    assert "OK records-v3" in verified.stdout
    assert "GoldenMismatch" not in verified.stdout
    assert "NotImplemented" not in verified.stdout


def test_10_1_the_repository_suite_still_describes_the_store():
    assert tables.READER_ACCEPTS == ("v1", "v2", "v3")
    assert tables.WRITER_EMITS == "v3"
    assert evolution.encode_row(Record.put("k", 1, written_at=5, writer="w", lsn=2)) == {
        "key": "k", "value": 1, "gen": 1, "vec": {"w": 1}, "deleted": False, "lsn": 2, "at": 5, "writer": "w", "attrs": [],
    }
    record = Record(key="k", value=None, generation=2, vector=VersionVector.new({"w": 2}), deleted=True, lsn=3, written_at=6, writer="w")
    assert evolution.decode_row(evolution.encode_row(record)) == record
