"""Schema evolution: versioned row layouts and the paths between them.

The contract is ``SPEC.md`` section 10 and the reasoning is in
``docs/schema-evolution.md`` and ``docs/adr/ADR-0010`` to ``ADR-0013``. This
module is the implementation of that contract: three row layouts, an upgrade
chain that runs on read, a downgrade chain that serves pinned readers, a
dual-write window for the migration, index projections, and the registration
of every step in the strategy registry.

Layouts are declared in ``schema/tables.json`` under ``layouts`` and reach
this module only through the generated :data:`atlas.tables.LAYOUTS`. The
frame bytes are produced by :func:`atlas.codec.encode`, never here: the
canonical form of the codec is frozen, and a golden digest pins it.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import tables
from .codec import FrameKind, canonical, decode, encode
from .errors import AtlasError, DuplicateKeyError
from .registry import StrategySet
from .values import Record
from .wal import Transaction, WriteAheadLog, record_from_payload

#: The layout a writer emits. Copied from the generated tables; never older.
CURRENT_VERSION: int = tables.SCHEMA_VERSION
#: The writer identifier a legacy row is given when its layout had none.
LEGACY_WRITER = "legacy"
#: Golden families ``tools/verify_goldens.py`` knows how to recompute.
GOLDEN_FAMILIES = ("records", "indexes")
#: Marker field of a dual-written shadow frame.
SHADOW_MARKER = "shadow"
GOLDENS_RELPATH = pathlib.Path("schema") / "goldens"


class EvolutionError(AtlasError):
    code = "evolution_error"


class UnknownLayoutError(EvolutionError):
    """A payload or a version number names no declared layout."""

    code = "unknown_layout"

    def __init__(self, version: object, known: Iterable[int]) -> None:
        self.version = version
        self.known = tuple(sorted(known))
        super().__init__(f"unknown row layout {version!r}; declared layouts: {list(self.known)}")


class CodecMismatchError(EvolutionError):
    """Bytes that should have been identical were not.

    Raised by :func:`verify_round_trip` when a frame that went up to the
    current layout and back down does not come back byte-for-byte, and by
    callers comparing a frame against a golden digest. The message is stable
    and is the signature a reader greps for::

        CodecMismatch(records-v1, expected=<sha256>, actual=<sha256>)

    The same message is produced by an unfinished downgrade and by a changed
    canonical form; telling the two apart is what ``ADR-0011`` is for.
    """

    code = "codec_mismatch"

    def __init__(self, name: str, expected: str, actual: str) -> None:
        self.name = name
        self.expected = expected
        self.actual = actual
        super().__init__(f"CodecMismatch({name}, expected={expected}, actual={actual})")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------- layouts
def layouts() -> dict[int, tuple[str, ...]]:
    """The declared layouts, version to payload fields, from the generated tables.

    Raises :class:`UnknownLayoutError` when the generated module declares no
    layouts: that means the schema document was changed without regenerating,
    or the layouts were never declared (``SPEC.md`` 10.2).
    """

    declared = getattr(tables, "LAYOUTS", None)
    if not declared:
        raise UnknownLayoutError("<none>", ())
    return {int(version): tuple(fields) for version, fields in declared.items()}


def detect_version(payload: dict) -> int:
    """Which declared layout a payload was written under.

    Detection is by field set and is total: the highest declared version whose
    fields are all present wins, and a payload that fits no layout raises
    :class:`UnknownLayoutError`. An explicit ``v`` tag, when present, is
    honoured first.
    """

    known = layouts()
    tagged = payload.get("v")
    if tagged is not None:
        version = int(tagged)
        if version not in known:
            raise UnknownLayoutError(version, known)
        return version
    present = set(payload)
    for version in sorted(known, reverse=True):
        if set(known[version]) <= present:
            return version
    raise UnknownLayoutError(sorted(present), known)


# ------------------------------------------------------------------- steps
def _text(value: Any) -> Any:
    return None if value is None else canonical(value).decode("utf-8")


def _untext(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _v1_to_v2(payload: dict) -> dict:
    return {
        "key": payload["key"],
        "value": _untext(payload.get("value")),
        "gen": int(payload.get("gen", 1)),
        "lsn": int(payload.get("lsn", 0)),
        "at": 0,
        "writer": LEGACY_WRITER,
    }


def _v2_to_v3(payload: dict) -> dict:
    writer = payload.get("writer") or LEGACY_WRITER
    generation = int(payload.get("gen", 1))
    return {
        "key": payload["key"],
        "value": payload.get("value"),
        "gen": generation,
        "vec": {writer: generation},
        "deleted": payload.get("value") is None,
        "lsn": int(payload.get("lsn", 0)),
        "at": int(payload.get("at", 0)),
        "writer": writer,
        "attrs": [],
    }


def _v3_to_v2(payload: dict) -> dict:
    return {
        "key": payload["key"],
        "value": None if payload.get("deleted") else payload.get("value"),
        "gen": int(payload.get("gen", 1)),
        "lsn": int(payload.get("lsn", 0)),
        "at": int(payload.get("at", 0)),
        "writer": payload.get("writer", ""),
    }


def _v2_to_v1(payload: dict) -> dict:
    return {
        "key": payload["key"],
        "value": _text(payload.get("value")),
        "gen": int(payload.get("gen", 1)),
        "lsn": int(payload.get("lsn", 0)),
    }


_STEPS = {
    (1, 2): _v1_to_v2,
    (2, 3): _v2_to_v3,
    (3, 2): _v3_to_v2,
    (2, 1): _v2_to_v1,
}


def step_name(source: int, target: int) -> str:
    return f"records:v{source}->v{target}"


def _step(source: int, target: int, strategies: StrategySet | None):
    if strategies is not None and strategies.evolution.has(step_name(source, target)):
        return strategies.evolution.resolve(step_name(source, target))
    try:
        return _STEPS[(source, target)]
    except KeyError:
        raise UnknownLayoutError(target, layouts()) from None


def upgrade(payload: dict, *, to: int = CURRENT_VERSION, strategies: StrategySet | None = None) -> dict:
    """Carry a payload forward, one declared step at a time, to ``to``."""

    known = layouts()
    if to not in known:
        raise UnknownLayoutError(to, known)
    version = detect_version(payload)
    current = dict(payload)
    current.pop("v", None)
    while version < to:
        current = _step(version, version + 1, strategies)(current)
        version += 1
    return current


def downgrade(payload: dict, *, to: int, strategies: StrategySet | None = None) -> dict:
    """Carry a payload back, one declared step at a time, to ``to``."""

    known = layouts()
    if to not in known:
        raise UnknownLayoutError(to, known)
    version = detect_version(payload)
    current = dict(payload)
    current.pop("v", None)
    while version > to:
        current = _step(version, version - 1, strategies)(current)
        version -= 1
    return current


# -------------------------------------------------------------------- rows
def encode_row(record: Record, *, version: int = CURRENT_VERSION) -> dict:
    """The payload of ``record`` at ``version``; the current layout, downgraded."""

    current = {
        "key": record.key,
        "value": record.value,
        "gen": record.generation,
        "vec": dict(record.vector.counters),
        "deleted": record.deleted,
        "lsn": record.lsn,
        "at": record.written_at,
        "writer": record.writer,
        "attrs": [list(pair) for pair in record.attributes],
    }
    if version == CURRENT_VERSION:
        return current
    return downgrade(current, to=version)


def decode_row(payload: dict, *, version: int | None = None) -> Record:
    """Read a payload written under any declared layout as a current record."""

    if version is not None and version != detect_version(payload):
        raise UnknownLayoutError(version, layouts())
    upgraded = upgrade(payload)
    return record_from_payload(upgraded)


def frame_for(record: Record, *, version: int = CURRENT_VERSION, kind: FrameKind = FrameKind.PUT) -> bytes:
    return encode(kind, encode_row(record, version=version))


def verify_round_trip(frame: bytes, *, name: str | None = None) -> Record:
    """Up to the current layout and back down must give the same bytes.

    Returns the upgraded record. Raises :class:`CodecMismatchError` named
    ``records-v<n>`` for the frame's own layout when the bytes differ.
    """

    decoded = decode(frame)
    version = detect_version(decoded.payload)
    upgraded = upgrade(decoded.payload)
    back = downgrade(upgraded, to=version)
    again = encode(decoded.kind, back)
    expected = sha256(frame[: decoded.size])
    actual = sha256(again)
    if expected != actual:
        raise CodecMismatchError(name or f"records-v{version}", expected, actual)
    return record_from_payload(upgraded)


# ------------------------------------------------------------------ readers
def read_log(directory: pathlib.Path | str) -> list[Record]:
    """Every record of every committed transaction, upgraded, in log order."""

    log = WriteAheadLog(directory, fsync=False, repair_on_open=False)
    records: list[Record] = []
    for _txn, _begin, frames in log.transactions():
        for kind, payload in frames:
            if kind not in (FrameKind.PUT, FrameKind.DELETE):
                continue
            record = decode_row(payload)
            if kind is FrameKind.DELETE and not record.deleted:
                record = Record(
                    key=record.key,
                    value=None,
                    generation=record.generation,
                    vector=record.vector,
                    deleted=True,
                    lsn=record.lsn,
                    written_at=record.written_at,
                    writer=record.writer,
                    attributes=record.attributes,
                )
            records.append(record)
    return records


def read_snapshot(path: pathlib.Path | str) -> list[Record]:
    """Every record of a snapshot file, upgraded, in file order."""

    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return [decode_row(item) for item in payload.get("records", ())]


class PinnedReader:
    """A reader that understands layouts up to ``version`` and nothing newer."""

    def __init__(self, version: int) -> None:
        if version not in layouts():
            raise UnknownLayoutError(version, layouts())
        self.version = int(version)

    def read(self, payload: dict) -> dict:
        """The payload as this reader sees it: downgraded to its version."""

        return downgrade(payload, to=self.version)

    def visible_rows(self, log: WriteAheadLog) -> dict[str, dict]:
        """Key to latest payload among frames this reader can decode.

        A PUT or DELETE frame is visible when its layout is at or below the
        pinned version; a shadow frame is visible when it was written for
        this version. Frames written under a newer layout are invisible, which
        is the gap dual-write exists to close.
        """

        visible: dict[str, dict] = {}
        for _txn, _begin, frames in log.transactions():
            for kind, payload in frames:
                if kind is FrameKind.CONTROL and payload.get(SHADOW_MARKER) == "records":
                    if int(payload.get("v", 0)) == self.version:
                        row = dict(payload["row"])
                        visible[row["key"]] = row
                    continue
                if kind not in (FrameKind.PUT, FrameKind.DELETE):
                    continue
                try:
                    version = detect_version(payload)
                except UnknownLayoutError:
                    continue
                if version <= self.version:
                    visible[payload["key"]] = dict(payload)
        return visible


# --------------------------------------------------------------- dual-write
def shadow_payload(record: Record, *, pinned: int) -> dict:
    return {
        SHADOW_MARKER: "records",
        "v": int(pinned),
        "lsn": record.lsn,
        "row": encode_row(record, version=pinned),
    }


@dataclass
class MigrationWindow:
    """Dual-write: every write made through the window is also persisted at ``pinned``.

    The current frame is written by the storage exactly as before; the window
    then appends one ``CONTROL`` shadow frame carrying the downgraded row in
    its own committed transaction. Recovery ignores control frames, so the
    window changes nothing the current reader sees.
    """

    storage: Any
    pinned: int
    shadows: int = 0
    open: bool = True
    written: list[Record] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.pinned not in layouts():
            raise UnknownLayoutError(self.pinned, layouts())
        if self.pinned >= CURRENT_VERSION:
            raise EvolutionError(f"a window pins an older layout, not v{self.pinned}")

    def put(self, key: str, value: Any, **options: Any) -> Record:
        record = self.storage.put(key, value, **options)
        self._shadow(record)
        return record

    def delete(self, key: str, **options: Any) -> Record:
        record = self.storage.delete(key, **options)
        self._shadow(record)
        return record

    def _shadow(self, record: Record) -> None:
        if not self.open:
            raise EvolutionError("the migration window is closed")
        transaction = Transaction(txn_id=f"shadow-{record.lsn}", lsn=record.lsn)
        transaction.control(shadow_payload(record, pinned=self.pinned))
        self.storage.log.append(transaction)
        self.shadows += 1
        self.written.append(record)

    def close(self) -> int:
        self.open = False
        return self.shadows


# ----------------------------------------------------------------- indexes
def _where(clause: str):
    clause = clause.strip()
    if not clause:
        return lambda record: True
    if clause == "deleted = false":
        return lambda record: not record.deleted
    if clause == "deleted = true":
        return lambda record: record.deleted
    raise EvolutionError(f"unsupported index predicate {clause!r}")


def project_index(name: str, records: Iterable[Record]) -> tuple[tuple[Any, ...], ...]:
    """The entries of the declared index ``name`` over ``records``.

    An entry is the index columns followed by the primary key when the key is
    not already a column; entries are sorted column by column, naturally within
    a type and by type rank across types (null, bool, number, text, other). A
    ``where`` clause filters rows. A unique index whose columns repeat raises
    :class:`DuplicateKeyError` naming the index and the repeated columns.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")

def _entry_key(entry: tuple[Any, ...]) -> tuple:
    """Natural order within a type, type rank across types: null, bool, number, text, other."""

    ranked = []
    for value in entry:
        if value is None:
            ranked.append((0, 0))
        elif isinstance(value, bool):
            ranked.append((1, int(value)))
        elif isinstance(value, (int, float)):
            ranked.append((2, value))
        elif isinstance(value, str):
            ranked.append((3, value))
        else:
            ranked.append((4, canonical(value)))
    return tuple(ranked)


def _column_value(record: Record, column: str) -> Any:
    if column == "attributes":
        return [list(pair) for pair in record.attributes]
    return getattr(record, column)


def index_frame(name: str, records: Iterable[Record]) -> bytes:
    """One ``CONTROL`` frame carrying the whole projection; the golden form."""

    raise NotImplementedError("schema evolution is declared, not implemented")

# ----------------------------------------------------------------- goldens
def goldens_dir(start: pathlib.Path | str | None = None) -> pathlib.Path:
    origin = pathlib.Path(start or __file__).resolve()
    for candidate in (
        origin.parent.parent.parent / GOLDENS_RELPATH,
        pathlib.Path.cwd() / GOLDENS_RELPATH,
    ):
        if candidate.is_dir():
            return candidate
    raise EvolutionError(f"no goldens directory at {GOLDENS_RELPATH}")


def golden_rows(path: pathlib.Path | str | None = None) -> list[Record]:
    """The fixed rows every golden is computed from (``schema/goldens/rows.json``)."""

    source = pathlib.Path(path) if path else goldens_dir() / "rows.json"
    items = json.loads(source.read_text(encoding="utf-8"))
    return [record_from_payload(item) for item in items]


def golden_bytes(name: str, rows: Iterable[Record]) -> bytes:
    """Recompute the bytes a golden pins: a record family or an index."""

    rows = list(rows)
    if name.startswith("records-v"):
        version = int(name[len("records-v"):])
        return b"".join(frame_for(row, version=version) for row in rows)
    if name.startswith("index-"):
        return index_frame(name[len("index-"):], rows)
    raise EvolutionError(f"unknown golden family for {name!r}")


# ---------------------------------------------------------------- registry
def install_upgraders(strategies: StrategySet) -> None:
    """Register every row step under ``records:v<a>->v<b>``; idempotent."""

    for (source, target), function in _STEPS.items():
        name = step_name(source, target)
        if strategies.evolution.has(name):
            continue
        strategies.evolution.register(
            name,
            (lambda fn: (lambda: fn))(function),
            description=f"row layout v{source} to v{target}",
        )


def install_indexes(strategies: StrategySet) -> None:
    """Register every declared index projection under ``index:<name>``; idempotent."""

    raise NotImplementedError("schema evolution is declared, not implemented")

