"""The acceptance suite for index evolution: SPEC.md section 10, the index half.

An index is declared in the schema document and nowhere else; its projection
over a set of rows is a pure function of the declaration and the rows, and
its golden frame pins the bytes. The tests check the new ``by_generation``
index, the three indexes the seed already declares, and the artefacts of the
procedure a schema change requires: the generated tables, the lock, and the
goldens, verified by the repository's own tools from the workspace root.
"""

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

from atlas import evolution, tables
from atlas.codec import FrameKind, decode
from atlas.errors import DuplicateKeyError
from atlas.registry import STRATEGIES, StrategySet
from atlas.schema import discover
from atlas.values import Record
from atlas.vclock import VersionVector

WORKSPACE = pathlib.Path.cwd()
GOLDENS = WORKSPACE / "schema" / "goldens"

EXPECTED_INDEXES = (
    ("by_writer", ("writer", "key"), False, ""),
    ("by_lsn", ("lsn",), True, ""),
    ("live_only", ("deleted", "key"), False, "deleted = false"),
    ("by_generation", ("generation", "key"), False, ""),
)
EXPECTED_GOLDENS = {
    "index-by_writer": "16f7c66bad48d96114727267714ed4f5f4f2c773ed760e7cd8c4fe9551750489",
    "index-by_lsn": "365ff7e05f854bdfc67280b594abcdf737f17d18ec6dd82e5969c639a47ea30d",
    "index-live_only": "5d254362905a7833c26e08c1468ca211981906fbe38421b4e90d205d94e5f183",
    "index-by_generation": "eb97dc5110f5f6565192c86cd6d58c6fde1001ae9b192ec9f56254dbea9e8958",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tool(*arguments):
    return subprocess.run(
        [sys.executable, str(WORKSPACE / "tools" / arguments[0]), *arguments[1:]],
        cwd=str(WORKSPACE),
        env={"PYTHONPATH": str(WORKSPACE / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
    )


def rows():
    return evolution.golden_rows(GOLDENS / "rows.json")


def record(key, value, *, generation=1, lsn=0, writer="w", deleted=False, attributes=None):
    return Record(
        key=key,
        value=None if deleted else value,
        generation=generation,
        vector=VersionVector.new({writer: generation}),
        deleted=deleted,
        lsn=lsn,
        written_at=0,
        writer=writer,
        attributes=tuple(sorted((attributes or {}).items())),
    )


# ------------------------------------------------------------ 10.10 declared
def test_10_10_the_index_is_declared_in_the_schema_document_and_generated():
    document = json.loads((WORKSPACE / "schema" / "tables.json").read_text(encoding="utf-8"))
    declared = [(item["name"], tuple(item["columns"]), bool(item.get("unique", False)), str(item.get("where", ""))) for item in document["indexes"]]
    assert tuple(declared) == EXPECTED_INDEXES
    assert tables.INDEXES == EXPECTED_INDEXES
    assert tables.index("by_generation") == ("by_generation", ("generation", "key"), False, "")
    schema = discover()
    assert [index.name for index in schema.indexes] == [item[0] for item in EXPECTED_INDEXES]
    assert schema.version == 3 and tables.SCHEMA_VERSION == 3
    assert tables.COLUMNS == (
        ("key", "str", True, 256), ("value", "json", False, 65536), ("generation", "int", False, 8), ("lsn", "int", False, 8),
        ("written_at", "int", False, 8), ("writer", "str", False, 64), ("deleted", "bool", False, 1), ("attributes", "pairs", False, 1024),
    )


# ---------------------------------------------------------- 10.11 projection
def test_10_11_entries_are_the_index_columns_then_the_key_sorted():
    data = [
        record("b", 1, generation=2, lsn=2, writer="n2"),
        record("a", 1, generation=1, lsn=1, writer="n2"),
        record("c", 1, generation=2, lsn=3, writer="n1"),
    ]
    assert evolution.project_index("by_writer", data) == (("n1", "c"), ("n2", "a"), ("n2", "b"))
    assert evolution.project_index("by_generation", data) == ((1, "a"), (2, "b"), (2, "c"))
    assert evolution.project_index("by_lsn", data) == ((1, "a"), (2, "b"), (3, "c"))
    assert evolution.project_index("live_only", data) == ((False, "a"), (False, "b"), (False, "c"))


def test_10_11_a_where_clause_filters_and_a_unique_index_refuses_a_repeat():
    data = [
        record("a", 1, lsn=1),
        record("b", None, lsn=2, deleted=True, generation=2),
        record("c", 1, lsn=3),
    ]
    assert evolution.project_index("live_only", data) == ((False, "a"), (False, "c"))
    assert evolution.project_index("by_generation", data) == ((1, "a"), (1, "c"), (2, "b"))
    with pytest.raises(DuplicateKeyError) as caught:
        evolution.project_index("by_lsn", data + [record("d", 1, lsn=3)])
    assert "by_lsn" in str(caught.value) and "3" in str(caught.value)
    # a non-unique index accepts a repeat
    assert evolution.project_index("by_generation", data + [record("d", 1, lsn=4)]) == ((1, "a"), (1, "c"), (1, "d"), (2, "b"))
    with pytest.raises(evolution.EvolutionError):
        evolution.project_index("no_such_index", data)


def test_10_11_the_projection_over_the_golden_rows_matches_the_goldens():
    golden = rows()
    assert len(golden) == 12
    for name, expected in EXPECTED_GOLDENS.items():
        frame = evolution.index_frame(name[len("index-"):], golden)
        assert sha256(frame) == expected, name
        decoded = decode(frame)
        assert decoded.kind is FrameKind.CONTROL
        assert decoded.payload["index"] == name[len("index-"):]
        assert len(decoded.payload["entries"]) == (10 if name == "index-live_only" else 12)
    by_generation = evolution.project_index("by_generation", golden)
    assert by_generation[0] == (1, "account:0001")
    assert by_generation[-1] == (7, "counter:hits")
    assert [entry[0] for entry in by_generation] == sorted(entry[0] for entry in by_generation)


# ------------------------------------------------------------- 10.8 registry
def test_10_8_every_declared_index_is_registered_once():
    fresh = StrategySet()
    evolution.install_indexes(fresh)
    assert fresh.evolution.names() == frozenset(f"index:{name}" for name, *_ in EXPECTED_INDEXES)
    evolution.install_indexes(fresh)
    assert len(fresh.evolution.names()) == 4
    projection = fresh.evolution.resolve("index:by_generation")
    assert projection([record("a", 1, generation=3)]) == ((3, "a"),)
    evolution.install_indexes(STRATEGIES)
    assert "index:by_generation" in STRATEGIES.evolution.names()


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


def test_10_9_the_goldens_include_the_new_index_and_verify_with_the_repository_tool():
    recorded = json.loads((GOLDENS / "GOLDENS.json").read_text(encoding="utf-8"))
    for name, expected in EXPECTED_GOLDENS.items():
        assert recorded.get(name) == expected, name
        assert sha256((GOLDENS / f"{name}.frame").read_bytes()) == expected, name
    assert {"records-v1", "records-v2", "records-v3"} <= set(recorded), "the row goldens must stay recorded"
    verified = tool("verify_goldens.py", "--family", "indexes")
    assert verified.returncode == 0, verified.stdout + verified.stderr
    for name in EXPECTED_GOLDENS:
        assert f"OK {name}" in verified.stdout
    assert "GoldenMismatch" not in verified.stdout
    assert "NotImplemented" not in verified.stdout
    listed = tool("verify_goldens.py", "--list")
    assert "index-by_generation" in listed.stdout
