"""Schema evolution: versioned row layouts and the paths between them.

.. note::
   **This feature is not implemented.** The functions and classes below
   declare the contract; every one that would do work raises
   ``NotImplementedError``. The contract is complete and normative: it says
   what a caller may expect, in the order the expectations hold, and an
   implementation is judged against it, not against these stubs. See
   ``SPEC.md`` section 10 for the acceptance rules,
   ``docs/schema-evolution.md`` for the procedure that accompanies any
   change to the schema, and ``docs/adr/ADR-0010`` to ``ADR-0013`` for the
   decisions behind both.

A stored row has a **layout**: the set of payload fields a frame carries. The
layout a writer emits today is the one the schema document calls version
``3``; two older layouts exist on disk in clusters that were rolled forward:

``v1``  the legacy flat layout: ``key``, ``value``, ``gen``, ``lsn``. The
        value is JSON *text*, not JSON; a ``null`` value is a tombstone.
``v2``  ``v1`` plus ``at`` (milliseconds) and ``writer``; the value is JSON.
``v3``  the current layout, what :func:`atlas.wal._record_payload` writes:
        ``v2`` plus ``vec``, ``deleted`` and ``attrs``.

Four things this module provides, and the order a migration uses them in:

* **on-read upgrade** — :func:`decode_row` reads a payload written under any
  declared layout and returns a current :class:`~atlas.values.Record`; the
  rows on disk are never rewritten (``ADR-0010``);
* **dual-write** — a :class:`MigrationWindow` persists every write at the
  current layout *and* at the layout a pinned reader understands, so that the
  reader sees new rows during the roll;
* **downgrade** — a :class:`PinnedReader` is served current rows downgraded
  to its own layout, and :func:`verify_round_trip` proves that a legacy frame
  survives the trip up and down byte-for-byte (``ADR-0013``);
* **registration** — every step is registered in the strategy registry under
  ``records:v<a>->v<b>`` so that a node lists what it can read, and every
  declared index projection under ``index:<name>``.

Layouts are declared in ``schema/tables.json`` under ``layouts`` and reach
this module only through the generated :data:`atlas.tables.LAYOUTS`; the
generator and its lock are the procedure in ``docs/schema-evolution.md``. The
frame bytes are produced by :func:`atlas.codec.encode`, never here: the
canonical form of the codec is frozen (``ADR-0011``) and the goldens under
``schema/goldens/`` pin it.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import tables
from .codec import FrameKind
from .errors import AtlasError
from .registry import StrategySet
from .values import Record
from .wal import WriteAheadLog, record_from_payload

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

    raise NotImplementedError("schema evolution is declared, not implemented")


def detect_version(payload: dict) -> int:
    """Which declared layout a payload was written under.

    Detection is by field set and is total: the highest declared version whose
    fields are all present wins, and a payload that fits no layout raises
    :class:`UnknownLayoutError`. An explicit ``v`` tag, when present, is
    honoured first.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


# ------------------------------------------------------------------- steps
def step_name(source: int, target: int) -> str:
    """The registry name of one evolution step: ``records:v<a>->v<b>``."""

    return f"records:v{source}->v{target}"


def upgrade(payload: dict, *, to: int = CURRENT_VERSION, strategies: StrategySet | None = None) -> dict:
    """Carry a payload forward, one declared step at a time, to ``to``.

    Steps are ``v1 -> v2`` (parse the value text, ``at := 0``, ``writer :=
    "legacy"``) and ``v2 -> v3`` (``vec := {writer: gen}``, ``deleted := value
    is null``, ``attrs := []``). With ``strategies`` given, a step registered
    there under :func:`step_name` is used in place of the built-in one.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


def downgrade(payload: dict, *, to: int, strategies: StrategySet | None = None) -> dict:
    """Carry a payload back, one declared step at a time, to ``to``.

    Steps are ``v3 -> v2`` (drop ``vec``, ``deleted``, ``attrs``; a tombstone
    becomes a ``null`` value) and ``v2 -> v1`` (drop ``at`` and ``writer``;
    the value becomes its canonical JSON text). Downgrade is lossy by design;
    what it must preserve is stated in ``SPEC.md`` 10.6.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


# -------------------------------------------------------------------- rows
def encode_row(record: Record, *, version: int = CURRENT_VERSION) -> dict:
    """The payload of ``record`` at ``version``: the current layout, downgraded."""

    raise NotImplementedError("schema evolution is declared, not implemented")


def decode_row(payload: dict, *, version: int | None = None) -> Record:
    """Read a payload written under any declared layout as a current record.

    This is the on-read upgrade. ``version``, when given, asserts the layout
    the caller expects and raises :class:`UnknownLayoutError` otherwise.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


def frame_for(record: Record, *, version: int = CURRENT_VERSION, kind: FrameKind = FrameKind.PUT) -> bytes:
    """One codec frame carrying ``record`` at ``version``; the golden form of a row."""

    raise NotImplementedError("schema evolution is declared, not implemented")


def verify_round_trip(frame: bytes, *, name: str | None = None) -> Record:
    """Up to the current layout and back down must give the same bytes.

    Returns the upgraded record. Raises :class:`CodecMismatchError` named
    ``records-v<n>`` for the frame's own layout when the bytes differ.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


# ------------------------------------------------------------------ readers
def read_log(directory: pathlib.Path | str) -> list[Record]:
    """Every record of every committed transaction, upgraded, in log order.

    A ``DELETE`` frame yields a tombstone whatever layout it was written in.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


def read_snapshot(path: pathlib.Path | str) -> list[Record]:
    """Every record of a snapshot file, upgraded, in file order."""

    raise NotImplementedError("schema evolution is declared, not implemented")


class PinnedReader:
    """A reader that understands layouts up to ``version`` and nothing newer."""

    def __init__(self, version: int) -> None:
        self.version = int(version)

    def read(self, payload: dict) -> dict:
        """The payload as this reader sees it: downgraded to its version."""

        raise NotImplementedError("schema evolution is declared, not implemented")

    def visible_rows(self, log: WriteAheadLog) -> dict[str, dict]:
        """Key to latest payload among frames this reader can decode.

        A PUT or DELETE frame is visible when its layout is at or below the
        pinned version; a shadow frame is visible when it was written for
        this version. Frames written under a newer layout are invisible, which
        is the gap dual-write exists to close.
        """

        raise NotImplementedError("schema evolution is declared, not implemented")


# --------------------------------------------------------------- dual-write
def shadow_payload(record: Record, *, pinned: int) -> dict:
    """The ``CONTROL`` payload of a dual-written row::

        {"shadow": "records", "v": <pinned>, "lsn": <lsn>, "row": <payload at pinned>}
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


@dataclass
class MigrationWindow:
    """Dual-write: every write made through the window is also persisted at ``pinned``.

    The current frame is written by the storage exactly as before; the window
    then appends one ``CONTROL`` shadow frame carrying the downgraded row in
    its own committed transaction. Recovery ignores control frames, so the
    window changes nothing the current reader sees. A window pins an older
    layout only; pinning the current one is an error.
    """

    storage: Any
    pinned: int
    shadows: int = 0
    open: bool = True
    written: list[Record] = field(default_factory=list)

    def put(self, key: str, value: Any, **options: Any) -> Record:
        raise NotImplementedError("schema evolution is declared, not implemented")

    def delete(self, key: str, **options: Any) -> Record:
        raise NotImplementedError("schema evolution is declared, not implemented")

    def close(self) -> int:
        """Close the window; return how many shadow frames it wrote."""

        raise NotImplementedError("schema evolution is declared, not implemented")


# ----------------------------------------------------------------- indexes
def project_index(name: str, records: Iterable[Record]) -> tuple[tuple[Any, ...], ...]:
    """The entries of the declared index ``name`` over ``records``.

    An entry is the index columns followed by the primary key when the key is
    not already a column; entries are sorted column by column, naturally within
    a type and by type rank across types (null, bool, number, text, other). A
    ``where`` clause filters rows (``deleted = false`` is the only predicate
    the schema uses). A unique index whose columns repeat raises
    :class:`~atlas.errors.DuplicateKeyError` naming the index and the repeated
    columns; an undeclared index name raises :class:`EvolutionError`.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


def index_frame(name: str, records: Iterable[Record]) -> bytes:
    """One ``CONTROL`` frame ``{"index": name, "entries": [...]}``; the golden form."""

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
    """Recompute the bytes a golden pins: a record family or an index.

    ``records-v<n>`` is the concatenation of :func:`frame_for` over the rows at
    version ``n``; ``index-<name>`` is :func:`index_frame`.
    """

    rows = list(rows)
    if name.startswith("records-v"):
        version = int(name[len("records-v"):])
        return b"".join(frame_for(row, version=version) for row in rows)
    if name.startswith("index-"):
        return index_frame(name[len("index-"):], rows)
    raise EvolutionError(f"unknown golden family for {name!r}")


# ---------------------------------------------------------------- registry
def install_upgraders(strategies: StrategySet) -> None:
    """Register every row step under ``records:v<a>->v<b>``; idempotent.

    A second installation into the same set registers nothing and raises
    nothing: the registry refuses duplicates, and the installer must check
    before it registers.
    """

    raise NotImplementedError("schema evolution is declared, not implemented")


def install_indexes(strategies: StrategySet) -> None:
    """Register every declared index projection under ``index:<name>``; idempotent."""

    raise NotImplementedError("schema evolution is declared, not implemented")
