#!/usr/bin/env python3
"""Rebuild the goldens, the reference trees and the hidden fixtures of the atlas-schema family.

Run from the repository root with the project interpreter::

    .venv/bin/python tests/fixtures/atlas_schema_solution/build_fixtures.py

What it produces, all deterministic:

* ``datasets/_sources/atlas/schema/goldens/{GOLDENS.json,*.frame}`` — the
  seed goldens (three row layouts, three declared indexes);
* ``tests/fixtures/atlas_schema_solution/001/`` — ``src/atlas/evolution.py``
  (rows implemented, indexes not), ``src/atlas/tables.py``, ``schema/MANIFEST``;
* ``tests/fixtures/atlas_schema_solution/002/`` — ``src/atlas/evolution.py``
  (indexes implemented, rows not), ``src/atlas/tables.py``, ``schema/MANIFEST``,
  ``schema/goldens/{GOLDENS.json,index-by_generation.frame}``;
* ``datasets/new_feature/atlas-schema-001/hidden_tests/fixtures/`` — a large
  v1 WAL, a large v2 snapshot, and ``expected.json`` with their digests.

``full_evolution.py`` beside this script is the complete implementation; the
two references are carved out of it by replacing bodies with
``NotImplementedError`` so that neither satisfies the other task.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
SEED = ROOT / "datasets" / "_sources" / "atlas"
TASK_001 = ROOT / "datasets" / "new_feature" / "atlas-schema-001"
PYTHON = sys.executable

ROW_FUNCTIONS = (
    "layouts",
    "detect_version",
    "upgrade",
    "downgrade",
    "encode_row",
    "decode_row",
    "frame_for",
    "verify_round_trip",
    "read_log",
    "read_snapshot",
    "shadow_payload",
    "install_upgraders",
)
ROW_METHODS = ("PinnedReader.read", "PinnedReader.visible_rows", "MigrationWindow.put",
               "MigrationWindow.delete", "MigrationWindow.close", "MigrationWindow.__post_init__")
INDEX_FUNCTIONS = ("project_index", "index_frame", "install_indexes")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stub_out(source: str, functions: tuple[str, ...], methods: tuple[str, ...] = ()) -> str:
    """Replace the body of each named top-level function / method with a raise."""

    lines = source.splitlines(keepends=True)

    def replace(start_pattern: str, indent: str) -> None:
        nonlocal lines
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(start_pattern, line):
                out.append(line)
                i += 1
                # keep the signature continuation and the docstring
                while i < len(lines) and not lines[i].startswith(indent + "    ") and lines[i].strip():
                    out.append(lines[i])
                    i += 1
                body_indent = indent + "    "
                if i < len(lines) and lines[i].lstrip().startswith('"""'):
                    out.append(lines[i])
                    if lines[i].count('"""') < 2:
                        i += 1
                        while '"""' not in lines[i]:
                            out.append(lines[i])
                            i += 1
                        out.append(lines[i])
                    i += 1
                    if i < len(lines) and not lines[i].strip():
                        out.append(lines[i])
                        i += 1
                out.append(f'{body_indent}raise NotImplementedError("schema evolution is declared, not implemented")\n')
                while i < len(lines) and (lines[i].startswith(body_indent) or not lines[i].strip()):
                    i += 1
                out.append("\n")
                continue
            out.append(line)
            i += 1
        lines = out

    for name in functions:
        replace(rf"^def {re.escape(name)}\(", "")
    for dotted in methods:
        _cls, method = dotted.split(".")
        replace(rf"^    def {re.escape(method)}\(", "    ")
    text = "".join(lines)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def make_workspace(tables_json: pathlib.Path, evolution_py: str) -> pathlib.Path:
    work = pathlib.Path(tempfile.mkdtemp(prefix="atlas-schema-build-"))
    shutil.copytree(SEED, work, dirs_exist_ok=True)
    shutil.copy2(tables_json, work / "schema" / "tables.json")
    (work / "src" / "atlas" / "evolution.py").write_text(evolution_py, encoding="utf-8")
    subprocess.run([PYTHON, "tools/gen_tables.py", "--lock"], cwd=work, check=True, capture_output=True)
    return work


def run(work: pathlib.Path, code: str) -> dict:
    completed = subprocess.run(
        [PYTHON, "-c", code],
        cwd=work,
        env={"PYTHONPATH": str(work / "src"), "PATH": "/usr/bin:/bin"},
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def build_goldens(work: pathlib.Path, names: list[str], target: pathlib.Path) -> dict[str, str]:
    target.mkdir(parents=True, exist_ok=True)
    result = run(
        work,
        f"""
import json, pathlib, sys
from atlas import evolution
rows = evolution.golden_rows(pathlib.Path({str(target / 'rows.json')!r}))
out = {{}}
for name in {names!r}:
    data = evolution.golden_bytes(name, rows)
    pathlib.Path({str(target)!r}, name + ".frame").write_bytes(data)
    out[name] = evolution.sha256(data)
print(json.dumps(out))
""",
    )
    return result


FIXTURE_CODE = r'''
import json, pathlib, random, hashlib
from atlas import evolution
from atlas.codec import FrameKind, encode, canonical
from atlas.wal import WriteAheadLog, Transaction

out_dir = pathlib.Path(__OUT_DIR__)
out_dir.mkdir(parents=True, exist_ok=True)
rng = random.Random(20261110)
WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india",
         "juliet", "kilo", "lima", "mike", "november", "oscar", "papa", "québec", "romeo",
         "sierra", "tango", "uniform", "victor", "whiskey", "x-ray", "yankee", "zulu", "ключ", "été"]

def value(i):
    kind = rng.randrange(6)
    if kind == 0:
        return {"id": i, "name": rng.choice(WORDS), "tags": rng.sample(WORDS, 3), "score": round(rng.random() * 100, 3)}
    if kind == 1:
        return [rng.randrange(1000) for _ in range(rng.randrange(1, 12))]
    if kind == 2:
        return " ".join(rng.choice(WORDS) for _ in range(rng.randrange(3, 40)))
    if kind == 3:
        return {"nested": {"deep": {"n": i, "f": rng.random(), "ok": bool(i % 2)}}, "z": None}
    if kind == 4:
        return rng.randrange(-10**9, 10**9)
    return {"blob": "".join(rng.choice("0123456789abcdef") for _ in range(rng.randrange(40, 400)))}

# ---- v1 WAL: two segments, transactions of 1..6 frames, one delete in 20 ----
wal_dir = out_dir / "v1-wal"
if wal_dir.exists():
    import shutil; shutil.rmtree(wal_dir)
log = WriteAheadLog(wal_dir, fsync=False, max_bytes=160 * 1024, repair_on_open=False)
lsn = 0
gens = {}
v1_payloads = []
txn = 0
while lsn < 1800:
    txn += 1
    begin = lsn + 1
    transaction = Transaction(txn_id=f"legacy-{txn:05d}", lsn=begin)
    for _ in range(rng.randrange(1, 7)):
        lsn += 1
        key = f"{rng.choice(WORDS)}:{rng.randrange(400):04d}"
        gens[key] = gens.get(key, 0) + 1
        delete = rng.random() < 0.05 and gens[key] > 1
        payload = {
            "key": key,
            "value": None if delete else canonical(value(lsn)).decode("utf-8"),
            "gen": gens[key],
            "lsn": lsn,
        }
        transaction.frames.append((FrameKind.DELETE if delete else FrameKind.PUT, payload))
        v1_payloads.append((FrameKind.DELETE if delete else FrameKind.PUT, payload))
    log.append(transaction)
# a torn tail on the last segment, so the reader must stop at the damage
last = log.segments[-1]
torn = Transaction(txn_id="legacy-torn", lsn=lsn + 1)
torn.frames.append((FrameKind.PUT, {"key": "torn:0000", "value": "\"lost\"", "gen": 1, "lsn": lsn + 1}))
log.append(torn, tear_bytes=17)

records = evolution.read_log(wal_dir)
assert len(records) == len(v1_payloads), (len(records), len(v1_payloads))
upgraded_digest = hashlib.sha256(b"".join(canonical(evolution.encode_row(r)) for r in records)).hexdigest()
latest = {}
for r in records:
    latest[r.key] = r
live = sorted(k for k, r in latest.items() if not r.deleted)
tomb = sorted(k for k, r in latest.items() if r.deleted)

# ---- v2 snapshot --------------------------------------------------------
writers = ["n1", "n2", "n3", "n4"]
v2_rows = []
for i in range(1, 1201):
    key = f"{rng.choice(WORDS)}:{i:05d}"
    deleted = rng.random() < 0.08
    v2_rows.append({
        "key": key,
        "value": None if deleted else value(100000 + i),
        "gen": rng.randrange(1, 9),
        "lsn": 5000 + i,
        "at": 1700000000000 + i * 1000,
        "writer": rng.choice(writers),
    })
snapshot = {"shard": 1, "last_lsn": 6200, "records": v2_rows}
snap_bytes = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
snap_path = out_dir / "v2-snapshot-000000006200.snap"
snap_path.write_bytes(snap_bytes)
v2_records = evolution.read_snapshot(snap_path)
v2_digest = hashlib.sha256(b"".join(canonical(evolution.encode_row(r)) for r in v2_records)).hexdigest()

# ---- round-trip frame fixtures: every frame of the first v1 segment --------
first = log.segments[0].read_bytes()
expected = {
    "v1_wal_records": len(records),
    "v1_wal_segments": len(log.segments),
    "v1_upgraded_sha256": upgraded_digest,
    "v1_live_keys": len(live),
    "v1_tombstone_keys": len(tomb),
    "v1_first_live_key": live[0],
    "v1_last_tombstone_key": tomb[-1],
    "v1_first_segment_sha256": hashlib.sha256(first).hexdigest(),
    "v2_snapshot_records": len(v2_records),
    "v2_upgraded_sha256": v2_digest,
    "v2_tombstones": sum(1 for r in v2_records if r.deleted),
    "v2_snapshot_sha256": hashlib.sha256(snap_bytes).hexdigest(),
}
(out_dir / "expected.json").write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
print(json.dumps({"wal_bytes": sum(p.stat().st_size for p in log.segments), "snap_bytes": len(snap_bytes), **expected}))
'''


def main() -> int:
    full = (HERE / "full_evolution.py").read_text(encoding="utf-8")
    rows_only = stub_out(full, INDEX_FUNCTIONS)
    indexes_only = stub_out(full, ROW_FUNCTIONS, ROW_METHODS)
    for text in (rows_only, indexes_only):
        compile(text, "evolution.py", "exec")

    # --- reference 001 ----------------------------------------------------
    ref1 = HERE / "001"
    work1 = make_workspace(ref1 / "schema" / "tables.json", full)
    (ref1 / "src" / "atlas").mkdir(parents=True, exist_ok=True)
    (ref1 / "src" / "atlas" / "evolution.py").write_text(rows_only, encoding="utf-8")
    shutil.copy2(work1 / "src" / "atlas" / "tables.py", ref1 / "src" / "atlas" / "tables.py")
    shutil.copy2(work1 / "schema" / "MANIFEST", ref1 / "schema" / "MANIFEST")

    # --- seed goldens (rows need layouts -> computed in work1) --------------
    seed_goldens = SEED / "schema" / "goldens"
    digests = build_goldens(
        work1,
        ["records-v1", "records-v2", "records-v3", "index-by_writer", "index-by_lsn", "index-live_only"],
        seed_goldens,
    )
    (seed_goldens / "GOLDENS.json").write_text(
        json.dumps({name: digests[name] for name in sorted(digests)}, indent=2) + "\n", encoding="utf-8"
    )

    # --- hidden fixtures of 001 --------------------------------------------
    fixtures = TASK_001 / "hidden_tests" / "fixtures"
    summary = run(work1, FIXTURE_CODE.replace("__OUT_DIR__", repr(str(fixtures))))
    print("fixtures:", json.dumps(summary, indent=2))

    # --- reference 002 ----------------------------------------------------
    ref2 = HERE / "002"
    work2 = make_workspace(ref2 / "schema" / "tables.json", full)
    (ref2 / "src" / "atlas").mkdir(parents=True, exist_ok=True)
    (ref2 / "src" / "atlas" / "evolution.py").write_text(indexes_only, encoding="utf-8")
    shutil.copy2(work2 / "src" / "atlas" / "tables.py", ref2 / "src" / "atlas" / "tables.py")
    shutil.copy2(work2 / "schema" / "MANIFEST", ref2 / "schema" / "MANIFEST")
    goldens2 = ref2 / "schema" / "goldens"
    goldens2.mkdir(parents=True, exist_ok=True)
    shutil.copy2(seed_goldens / "rows.json", goldens2 / "rows.json")
    extra = build_goldens(work2, ["index-by_generation"], goldens2)
    (goldens2 / "rows.json").unlink()
    merged = {**digests, **extra}
    (goldens2 / "GOLDENS.json").write_text(
        json.dumps({name: merged[name] for name in sorted(merged)}, indent=2) + "\n", encoding="utf-8"
    )
    print("goldens:", json.dumps(merged, indent=2))
    shutil.rmtree(work1)
    shutil.rmtree(work2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
