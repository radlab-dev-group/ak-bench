#!/usr/bin/env python3
"""Generate ``src/atlas/tables.py`` from ``schema/tables.json`` and lock it.

This is the generator. ``python -m atlas.tables`` only *reports* drift; it has
never written a byte, whatever its ``--write`` flag suggests. The procedure
that makes a schema change real is in ``docs/schema-evolution.md``; this tool
is its first step and its last check.

::

    python tools/gen_tables.py            # print what would change, exit 1 on drift
    python tools/gen_tables.py --stdout   # the generated module on stdout
    python tools/gen_tables.py --lock     # rewrite tables.py and schema/MANIFEST
    python tools/gen_tables.py --check    # exit 1 unless tables.py and MANIFEST
                                          # are exactly what this tool produces

The generated module is a pure function of the schema document and of
``GENERATOR_VERSION``. ``--lock`` records the sha256 of both inputs and
outputs in ``schema/MANIFEST`` so that a later ``--check`` can tell a
regenerated tree from a hand-edited one without a human reading the diff.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "tables.json"
TABLES_PATH = ROOT / "src" / "atlas" / "tables.py"
MANIFEST_PATH = ROOT / "schema" / "MANIFEST"

#: Bump when the template below changes in a way that alters the output for an
#: unchanged schema document. The manifest records it so a check can say "your
#: generator is older than the lock" instead of "mismatch".
GENERATOR_VERSION = 1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_document(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- template
def _py(value) -> str:
    """A Python literal in the house style: double-quoted strings."""

    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def _tuple_literal(items) -> str:
    items = tuple(items)
    if len(items) == 1:
        return f"({_py(items[0])},)"
    return "(" + ", ".join(_py(item) for item in items) + ")"


def render(document: dict) -> str:
    """The whole ``atlas/tables.py`` for ``document``. Deterministic."""

    version = int(document.get("version", 1))
    columns = [
        (
            item["name"],
            item["type"],
            bool(item.get("primary", False)),
            int(item.get("width", 0)),
        )
        for item in document.get("columns", ())
    ]
    indexes = [
        (
            item["name"],
            tuple(item["columns"]),
            bool(item.get("unique", False)),
            str(item.get("where", "")),
        )
        for item in document.get("indexes", ())
    ]
    limits = dict(document.get("limits", {}))
    compatibility = dict(document.get("compatibility", {}))
    reader_accepts = tuple(compatibility.get("reader_must_accept", (f"v{version}",)))
    writer_emits = str(compatibility.get("writer_emits", f"v{version}"))
    layouts = document.get("layouts")
    primary = next((name for name, _kind, is_primary, _width in columns if is_primary), "key")

    out: list[str] = []
    w = out.append
    w('"""GENERATED FILE -- DO NOT EDIT.')
    w("")
    w(f"Source: ``schema/tables.json`` (schema version {version}).")
    w("Generator: ``python tools/gen_tables.py --lock``")
    w("")
    w("Every line of this module is derived. A hand edit here is not a fix: it is")
    w("overwritten the next time the tables are generated, and the diff that")
    w("reintroduces it is the kind nobody wants to read at 3 a.m. Change the JSON")
    w("document and regenerate; that is also how the change reaches the other")
    w("artefacts that are derived from the same document.")
    w("")
    w("The column tables below describe the wire row of a stored record. They are")
    w("byte-for-byte what :mod:`atlas.schema` loaded at startup, which is exactly")
    w("why they are not computed at runtime: the generated form is what a code")
    w("reader sees, and a reader needs to see the row layout without opening two")
    w("files and running a program.")
    w('"""')
    w("")
    w("from __future__ import annotations")
    w("")
    w("from dataclasses import dataclass")
    w("from typing import Any, Iterator")
    w("")
    w("#: Bump only by regenerating; the value is copied from the schema document.")
    w(f"SCHEMA_VERSION = {version}")
    w("")
    w("COLUMNS: tuple[tuple[str, str, bool, int], ...] = (")
    for name, kind, is_primary, width in columns:
        w(f"    ({_py(name)}, {_py(kind)}, {_py(is_primary)}, {width}),")
    w(")")
    w("")
    w("INDEXES: tuple[tuple[str, tuple[str, ...], bool, str], ...] = (")
    for name, index_columns, unique, where in indexes:
        w(f"    ({_py(name)}, {_tuple_literal(index_columns)}, {_py(unique)}, {_py(where)}),")
    w(")")
    w("")
    w("LIMITS: dict[str, int] = {")
    for name, value in limits.items():
        w(f"    {_py(name)}: {int(value)},")
    w("}")
    w("")
    w("#: Rows a reader must accept. Asymmetric with what a writer emits; see")
    w("#: :meth:`atlas.schema.Schema.writer_emits`.")
    w(f"READER_ACCEPTS: tuple[str, ...] = {_tuple_literal(reader_accepts)}")
    w(f"WRITER_EMITS: str = {_py(writer_emits)}")
    if layouts:
        w("")
        w("#: Row layouts by version: the payload fields a row carries when it is")
        w("#: written under that version. Declared in the schema document under")
        w("#: ``layouts``; :mod:`atlas.evolution` upgrades and downgrades between them.")
        w("LAYOUTS: dict[int, tuple[str, ...]] = {")
        for key in sorted(layouts, key=lambda item: int(str(item).lstrip("v"))):
            number = int(str(key).lstrip("v"))
            fields = layouts[key]["fields"] if isinstance(layouts[key], dict) else layouts[key]
            w(f"    {number}: {_tuple_literal(fields)},")
        w("}")
    w("")
    w("COLUMN_NAMES: tuple[str, ...] = tuple(column[0] for column in COLUMNS)")
    w(f"PRIMARY_COLUMN: str = {_py(primary)}")
    w("")
    w("")
    w("@dataclass(frozen=True)")
    w("class Row:")
    w('    """The generated row shape. Field order is the wire order."""')
    w("")
    for name, kind, is_primary, _width in columns:
        annotation, default = _field(kind)
        if is_primary:
            w(f"    {name}: str")
        else:
            w(f"    {name}: {annotation} = {default}")
    w("")
    w("    def as_dict(self) -> dict[str, Any]:")
    w("        return {name: getattr(self, name) for name in COLUMN_NAMES}")
    w("")
    w("    @classmethod")
    w('    def from_dict(cls, payload: dict[str, Any]) -> "Row":')
    w("        missing = [name for name in (PRIMARY_COLUMN,) if name not in payload]")
    w("        if missing:")
    w('            raise ValueError(f"row is missing required column(s): {missing}")')
    w("        return cls(")
    for name, kind, is_primary, _width in columns:
        if is_primary:
            w(f"            {name}=payload[{_py(name)}],")
        else:
            w(f"            {name}={_coerce(name, kind)},")
    w("        )")
    w("")
    w("")
    w("def column(name: str) -> tuple[str, str, bool, int]:")
    w("    for item in COLUMNS:")
    w("        if item[0] == name:")
    w("            return item")
    w("    raise KeyError(name)")
    w("")
    w("")
    w("def index(name: str) -> tuple[str, tuple[str, ...], bool, str]:")
    w("    for item in INDEXES:")
    w("        if item[0] == name:")
    w("            return item")
    w("    raise KeyError(name)")
    w("")
    w("")
    w("def rows(records) -> Iterator[Row]:")
    w("    for record in records:")
    w("        yield Row(")
    for name, _kind, _is_primary, _width in columns:
        w(f"            {name}=record.{name},")
    w("        )")
    w("")
    w("")
    w("def render() -> str:  # pragma: no cover - regenerated, kept for parity checks")
    w('    lines = [f"# atlas tables v{SCHEMA_VERSION}"]')
    w("    for name, kind, primary, width in COLUMNS:")
    w('        marker = " *" if primary else ""')
    w('        lines.append(f"{name}: {kind}({width}){marker}")')
    w('    return "\\n".join(lines)')
    w("")
    w("")
    w("def main(argv=None) -> int:  # pragma: no cover - generator entry point")
    w('    """Report whether this module is stale against ``schema/tables.json``.')
    w("")
    w("    This entry point only reads. Regenerating is the job of")
    w("    ``tools/gen_tables.py --lock``, which also rewrites ``schema/MANIFEST``;")
    w("    a module that is regenerated without the lock is stale in a way this")
    w("    check cannot see.")
    w('    """')
    w("")
    w("    import argparse")
    w("")
    w("    from . import schema as schema_module")
    w("")
    w('    parser = argparse.ArgumentParser(prog="atlas.tables")')
    w('    parser.add_argument("--write", action="store_true", help="(no-op) use tools/gen_tables.py --lock")')
    w('    parser.add_argument("--schema", default=None, help="schema document to read")')
    w("    arguments = parser.parse_args(argv)")
    w("    loaded = schema_module.load(arguments.schema) if arguments.schema else schema_module.discover()")
    w("    drift = [")
    w("        column_name")
    w("        for column_name, (name, kind, primary, width) in zip(")
    w("            COLUMN_NAMES, COLUMNS")
    w("        )")
    w("        if (name, kind, primary, width)")
    w("        != next(")
    w("            (")
    w("                (item.name, item.type, item.primary, item.width)")
    w("                for item in loaded.columns")
    w("                if item.name == name")
    w("            ),")
    w("            None,")
    w("        )")
    w("    ]")
    w("    if loaded.version != SCHEMA_VERSION or drift:")
    w("        print(")
    w('            f"generated module is stale: schema v{loaded.version} vs v{SCHEMA_VERSION}"')
    w('            + (f", drifting columns: {drift}" if drift else "")')
    w("        )")
    w('        print("regenerate with: python tools/gen_tables.py --lock")')
    w("        return 1")
    w('    print(f"tables v{SCHEMA_VERSION} match schema/tables.json")')
    w("    return 0")
    w("")
    w("")
    w('if __name__ == "__main__":  # pragma: no cover')
    w("    raise SystemExit(main())")
    return "\n".join(out) + "\n"


def _field(kind: str) -> tuple[str, str]:
    return {
        "str": ("str", '""'),
        "int": ("int", "0"),
        "bool": ("bool", "False"),
        "json": ("Any", "None"),
        "pairs": ("tuple[tuple[str, str], ...]", "()"),
    }.get(kind, ("Any", "None"))


def _coerce(name: str, kind: str) -> str:
    key = _py(name)
    if kind == "str":
        return f'payload.get({key}, "")'
    if kind == "int":
        return f"int(payload.get({key}, 0))"
    if kind == "bool":
        return f"bool(payload.get({key}, False))"
    if kind == "pairs":
        return f"tuple(tuple(pair) for pair in payload.get({key}, ()))"
    return f"payload.get({key})"


# ----------------------------------------------------------------- manifest
def render_manifest(document_bytes: bytes, module_bytes: bytes, version: int) -> str:
    lines = [
        "# atlas schema lock -- written by tools/gen_tables.py --lock; do not edit",
        f"schema_version={version}",
        f"generator_version={GENERATOR_VERSION}",
        f"tables_json_sha256={sha256(document_bytes)}",
        f"tables_py_sha256={sha256(module_bytes)}",
    ]
    return "\n".join(lines) + "\n"


def parse_manifest(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _sep, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def check(schema_path: pathlib.Path, tables_path: pathlib.Path, manifest_path: pathlib.Path) -> list[str]:
    """Every way the tree can disagree with the generator, as messages."""

    problems: list[str] = []
    document_bytes = schema_path.read_bytes()
    document = json.loads(document_bytes.decode("utf-8"))
    expected = render(document).encode("utf-8")
    actual = tables_path.read_bytes() if tables_path.exists() else b""
    if actual != expected:
        problems.append(
            f"TablesDrift({tables_path.name}, expected={sha256(expected)}, actual={sha256(actual)})"
        )
    if not manifest_path.exists():
        problems.append(f"ManifestMissing({manifest_path.as_posix()})")
        return problems
    recorded = parse_manifest(manifest_path.read_text(encoding="utf-8"))
    wanted = parse_manifest(render_manifest(document_bytes, expected, int(document.get("version", 1))))
    for key, value in wanted.items():
        if recorded.get(key) != value:
            problems.append(
                f"ManifestMismatch({key}, expected={value}, actual={recorded.get(key, '<missing>')})"
            )
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gen_tables.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--schema", type=pathlib.Path, default=SCHEMA_PATH)
    parser.add_argument("--tables", type=pathlib.Path, default=TABLES_PATH)
    parser.add_argument("--manifest", type=pathlib.Path, default=MANIFEST_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stdout", action="store_true", help="print the generated module")
    mode.add_argument("--lock", action="store_true", help="write tables.py and the MANIFEST")
    mode.add_argument("--check", action="store_true", help="verify tables.py and the MANIFEST")
    arguments = parser.parse_args(argv)

    document_bytes = arguments.schema.read_bytes()
    document = json.loads(document_bytes.decode("utf-8"))
    generated = render(document)

    if arguments.stdout:
        sys.stdout.write(generated)
        return 0
    if arguments.lock:
        arguments.tables.write_text(generated, encoding="utf-8")
        manifest = render_manifest(document_bytes, generated.encode("utf-8"), int(document.get("version", 1)))
        arguments.manifest.parent.mkdir(parents=True, exist_ok=True)
        arguments.manifest.write_text(manifest, encoding="utf-8")
        print(f"wrote {arguments.tables} ({sha256(generated.encode('utf-8'))[:12]})")
        print(f"wrote {arguments.manifest}")
        return 0
    problems = check(arguments.schema, arguments.tables, arguments.manifest)
    if problems:
        for problem in problems:
            print(problem)
        if arguments.check:
            print("tables are not locked; see docs/schema-evolution.md")
        return 1
    print(f"tables v{document.get('version')} are locked (generator v{GENERATOR_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
