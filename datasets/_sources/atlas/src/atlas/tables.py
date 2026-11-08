"""GENERATED FILE -- DO NOT EDIT.

Source: ``schema/tables.json`` (schema version 3).
Generator: ``python -m atlas.tables --write``

Every line of this module is derived. A hand edit here is not a fix: it is
overwritten the next time the tables are generated, and the diff that
reintroduces it is the kind nobody wants to read at 3 a.m. Change the JSON
document and regenerate; that is also how the change reaches the other
artefacts that are derived from the same document.

The column tables below describe the wire row of a stored record. They are
byte-for-byte what :mod:`atlas.schema` loaded at startup, which is exactly
why they are not computed at runtime: the generated form is what a code
reader sees, and a reader needs to see the row layout without opening two
files and running a program.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

#: Bump only by regenerating; the value is copied from the schema document.
SCHEMA_VERSION = 3

COLUMNS: tuple[tuple[str, str, bool, int], ...] = (
    ("key", "str", True, 256),
    ("value", "json", False, 65536),
    ("generation", "int", False, 8),
    ("lsn", "int", False, 8),
    ("written_at", "int", False, 8),
    ("writer", "str", False, 64),
    ("deleted", "bool", False, 1),
    ("attributes", "pairs", False, 1024),
)

INDEXES: tuple[tuple[str, tuple[str, ...], bool, str], ...] = (
    ("by_writer", ("writer", "key"), False, ""),
    ("by_lsn", ("lsn",), True, ""),
    ("live_only", ("deleted", "key"), False, "deleted = false"),
)

LIMITS: dict[str, int] = {
    "max_key_bytes": 256,
    "max_value_bytes": 65536,
    "max_attributes": 32,
    "max_generation": 9007199254740991,
}

#: Rows a reader must accept. Asymmetric with what a writer emits; see
#: :meth:`atlas.schema.Schema.writer_emits`.
READER_ACCEPTS: tuple[str, ...] = ("v1", "v2", "v3")
WRITER_EMITS: str = "v3"

COLUMN_NAMES: tuple[str, ...] = tuple(column[0] for column in COLUMNS)
PRIMARY_COLUMN: str = "key"


@dataclass(frozen=True)
class Row:
    """The generated row shape. Field order is the wire order."""

    key: str
    value: Any = None
    generation: int = 0
    lsn: int = 0
    written_at: int = 0
    writer: str = ""
    deleted: bool = False
    attributes: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in COLUMN_NAMES}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Row":
        missing = [name for name in (PRIMARY_COLUMN,) if name not in payload]
        if missing:
            raise ValueError(f"row is missing required column(s): {missing}")
        return cls(
            key=payload["key"],
            value=payload.get("value"),
            generation=int(payload.get("generation", 0)),
            lsn=int(payload.get("lsn", 0)),
            written_at=int(payload.get("written_at", 0)),
            writer=payload.get("writer", ""),
            deleted=bool(payload.get("deleted", False)),
            attributes=tuple(tuple(pair) for pair in payload.get("attributes", ())),
        )


def column(name: str) -> tuple[str, str, bool, int]:
    for item in COLUMNS:
        if item[0] == name:
            return item
    raise KeyError(name)


def index(name: str) -> tuple[str, tuple[str, ...], bool, str]:
    for item in INDEXES:
        if item[0] == name:
            return item
    raise KeyError(name)


def rows(records) -> Iterator[Row]:
    for record in records:
        yield Row(
            key=record.key,
            value=record.value,
            generation=record.generation,
            lsn=record.lsn,
            written_at=record.written_at,
            writer=record.writer,
            deleted=record.deleted,
            attributes=record.attributes,
        )


def render() -> str:  # pragma: no cover - regenerated, kept for parity checks
    lines = [f"# atlas tables v{SCHEMA_VERSION}"]
    for name, kind, primary, width in COLUMNS:
        marker = " *" if primary else ""
        lines.append(f"{name}: {kind}({width}){marker}")
    return "\n".join(lines)


def main(argv=None) -> int:  # pragma: no cover - generator entry point
    """Regenerate this module from ``schema/tables.json``.

    Run it after editing the JSON. It prints what changed and rewrites this
    file only when asked, so a stray invocation cannot silently touch the
    tree.
    """

    import argparse

    from . import schema as schema_module

    parser = argparse.ArgumentParser(prog="atlas.tables")
    parser.add_argument("--write", action="store_true", help="rewrite this module")
    parser.add_argument("--schema", default=None, help="schema document to read")
    arguments = parser.parse_args(argv)
    loaded = schema_module.load(arguments.schema) if arguments.schema else schema_module.discover()
    drift = [
        column_name
        for column_name, (name, kind, primary, width) in zip(
            COLUMN_NAMES, COLUMNS
        )
        if (name, kind, primary, width)
        != next(
            (
                (item.name, item.type, item.primary, item.width)
                for item in loaded.columns
                if item.name == name
            ),
            None,
        )
    ]
    if loaded.version != SCHEMA_VERSION or drift:
        print(
            f"generated module is stale: schema v{loaded.version} vs v{SCHEMA_VERSION}"
            + (f", drifting columns: {drift}" if drift else "")
        )
        print("regenerate with: python -m atlas.tables --write")
        return 1
    print(f"tables v{SCHEMA_VERSION} match schema/tables.json")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
