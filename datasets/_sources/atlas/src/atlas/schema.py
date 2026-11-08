"""Schema definitions: the shape of a stored row, and what a reader must accept.

The schema lives in ``schema/tables.json`` and :mod:`atlas.tables` is
generated from it. This module is the hand-written half: it loads the
document, validates it, and answers the questions the write path asks before
it accepts a value — is this key too long, is this attribute set too wide, is
this generation representable.

The compatibility rule is asymmetric and that asymmetry is the contract: a
reader accepts v1, v2 and v3 rows, and a writer emits v3 only. A reader that
rejects a v2 row is broken; a writer that emits a v2 row is broken. Getting
the direction wrong is invisible in a single-process test, where reader and
writer are the same code, and shows up the first time an upgraded node meets
a snapshot written by a node that is still being rolled.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ConfigError

#: Where the authoritative schema document lives, relative to the package root.
SCHEMA_RELPATH = pathlib.Path("schema") / "tables.json"
SUPPORTED_READ = ("v1", "v2", "v3")


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    primary: bool = False
    width: int = 0

    def accepts(self, value: Any) -> bool:
        if self.type == "str":
            return isinstance(value, str)
        if self.type == "int":
            return isinstance(value, int) and not isinstance(value, bool)
        if self.type == "bool":
            return isinstance(value, bool)
        if self.type in ("json", "pairs"):
            return True
        return False


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]
    unique: bool = False
    where: str = ""


@dataclass(frozen=True)
class Schema:
    version: int
    columns: tuple[Column, ...]
    indexes: tuple[Index, ...]
    limits: Mapping[str, int] = field(default_factory=dict)
    compatibility: Mapping[str, Any] = field(default_factory=dict)

    def column(self, name: str) -> Column:
        for column in self.columns:
            if column.name == name:
                return column
        raise ConfigError(f"schema has no column {name!r}")

    @property
    def primary(self) -> Column:
        for column in self.columns:
            if column.primary:
                return column
        raise ConfigError("schema declares no primary column")

    def validate_row(self, row: Mapping[str, Any]) -> list[str]:
        """Return a list of reasons this row would be rejected; empty means valid."""

        problems: list[str] = []
        names = {column.name for column in self.columns}
        for name in row:
            if name not in names:
                problems.append(f"unknown column {name!r}")
        key = row.get("key")
        if not isinstance(key, str) or not key:
            problems.append("key is required and must be a non-empty string")
        elif len(key.encode("utf-8")) > int(self.limits.get("max_key_bytes", 256)):
            problems.append("key exceeds max_key_bytes")
        value = row.get("value")
        if value is not None and len(json.dumps(value)) > int(self.limits.get("max_value_bytes", 65536)):
            problems.append("value exceeds max_value_bytes")
        for column in self.columns:
            if column.name in row and not column.accepts(row[column.name]):
                problems.append(f"{column.name} must hold {column.type}")
        attributes = row.get("attributes")
        if attributes is not None and len(attributes) > int(self.limits.get("max_attributes", 32)):
            problems.append("too many attributes")
        generation = row.get("generation")
        if isinstance(generation, int) and generation > int(
            self.limits.get("max_generation", 9007199254740991)
        ):
            problems.append("generation exceeds the representable maximum")
        return problems

    def reader_accepts(self, version: str) -> bool:
        """Whether a reader of this schema may read ``version`` rows."""

        return version in SUPPORTED_READ

    def writer_emits(self) -> str:
        """What this schema writes. It is always the current version, never older."""

        declared = str(self.compatibility.get("writer_emits", f"v{self.version}"))
        if declared != f"v{self.version}":
            raise ConfigError(
                f"schema v{self.version} must write v{self.version}, not {declared!r}"
            )
        return declared


def load(path: pathlib.Path | str) -> Schema:
    document = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    columns = tuple(
        Column(
            name=item["name"],
            type=item["type"],
            primary=bool(item.get("primary", False)),
            width=int(item.get("width", 0)),
        )
        for item in document.get("columns", ())
    )
    indexes = tuple(
        Index(
            name=item["name"],
            columns=tuple(item["columns"]),
            unique=bool(item.get("unique", False)),
            where=str(item.get("where", "")),
        )
        for item in document.get("indexes", ())
    )
    return Schema(
        version=int(document.get("version", 1)),
        columns=columns,
        indexes=indexes,
        limits=dict(document.get("limits", {})),
        compatibility=dict(document.get("compatibility", {})),
    )


def discover(start: pathlib.Path | str | None = None) -> Schema:
    """Find the schema document, looking beside the package and above it."""

    origin = pathlib.Path(start or __file__).resolve()
    for candidate in (
        origin.parent.parent.parent / SCHEMA_RELPATH,
        origin.parent / SCHEMA_RELPATH,
        pathlib.Path.cwd() / SCHEMA_RELPATH,
    ):
        if candidate.exists():
            return load(candidate)
    raise ConfigError(f"no schema document at {SCHEMA_RELPATH} relative to {origin}")
