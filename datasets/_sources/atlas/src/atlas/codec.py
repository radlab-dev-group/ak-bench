"""Frame encoding: canonical JSON payloads with CRC-32C style checksums.

Two things make this module more than ``json.dumps``:

* encoding is **canonical** (sorted keys, no incidental whitespace), so the
  same logical frame always yields the same bytes and therefore the same
  checksum, which is what lets two replicas compare frames cheaply;
* the checksum covers the *header plus payload*, including the length, so a
  truncated tail cannot present a valid checksum for the bytes it did get.

Frame layout::

    magic       4 bytes  b"ATL1"
    kind        1 byte   FrameKind
    length      4 bytes  big-endian unsigned payload length
    crc         4 bytes  big-endian checksum over magic..payload
    payload     `length` bytes canonical JSON

The checksum function is :func:`checksum`, deliberately not ``zlib.crc32``:
it is a documented, dependency-free rolling sum, and changing it silently
breaks every frame on disk.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .errors import ChecksumMismatchError, TornFrameError

MAGIC = b"ATL1"
_HEADER = struct.Struct(">4sBI")
#: Bytes between the start of one frame and the start of its payload.
PAYLOAD_OFFSET = _HEADER.size + 4
#: Bytes of a frame that the checksum covers: magic, kind, length, payload.
HEADER_SIZE = _HEADER.size
#: The smallest frame that can exist on disk: header, checksum, no payload.
FRAME_OVERHEAD = PAYLOAD_OFFSET
MAX_FRAME_BYTES = 64 * 1024 * 1024
_POLYNOMIAL = 0x82F63B78


class FrameKind(IntEnum):
    BEGIN = 1
    PUT = 2
    DELETE = 3
    COMMIT = 4
    CONTROL = 5
    SNAPSHOT_REF = 6


@dataclass(frozen=True)
class Frame:
    kind: FrameKind
    payload: dict[str, Any]
    offset: int = 0
    size: int = 0

    @property
    def is_transaction_marker(self) -> bool:
        return self.kind in (FrameKind.BEGIN, FrameKind.COMMIT)


def canonical(value: Any) -> bytes:
    """A stable byte form of ``value``: sorted keys, ASCII preserved, tight separators."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_fallback
    ).encode("utf-8")


def _fallback(obj):
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=repr)
    if hasattr(obj, "__dict__"):
        return {key: value for key, value in sorted(vars(obj).items()) if not key.startswith("_")}
    return repr(obj)


def checksum(data: bytes) -> int:
    """The rolling checksum every frame carries.

    ``state = (state ^ byte) * PRIME`` rotated, then folded. Pure integer
    arithmetic so it is identical on every platform, and order sensitive.
    """

    state = 0x0BAD_CAFE
    prime = 0x0100_0193
    for byte in data:
        state ^= byte
        state = (state * prime) & 0xFFFF_FFFF
        state = ((state << 5) | (state >> 27)) & 0xFFFF_FFFF
    return state ^ (state >> 16)


def encode(kind: FrameKind, payload: dict[str, Any]) -> bytes:
    body = canonical(payload)
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError(f"frame payload of {len(body)} bytes exceeds the ceiling")
    head = _HEADER.pack(MAGIC, int(kind), len(body))
    digest = checksum(head + body)
    return head + struct.pack(">I", digest) + body


def decode(data: bytes, *, offset: int = 0, strict: bool = True) -> Frame:
    """Decode one frame from ``data`` at ``offset``.

    Raises :class:`TornFrameError` when the bytes run out before a complete
    frame, and :class:`ChecksumMismatchError` when a complete frame carries a
    checksum that does not match. Callers repairing a torn tail treat the two
    identically; callers validating an intact file must not.
    """

    if len(data) - offset < FRAME_OVERHEAD:
        raise TornFrameError("header is truncated")
    magic, kind_value, length = _HEADER.unpack_from(data, offset)
    if magic != MAGIC:
        raise TornFrameError(f"bad magic at offset {offset}: {magic!r}")
    if length > MAX_FRAME_BYTES:
        raise TornFrameError(f"declared frame length {length} is not plausible")
    end = offset + FRAME_OVERHEAD + length
    if len(data) < end:
        raise TornFrameError(f"payload is truncated at offset {offset}")
    digest_bytes = data[offset + HEADER_SIZE : offset + PAYLOAD_OFFSET]
    head = data[offset : offset + HEADER_SIZE]
    body = data[offset + PAYLOAD_OFFSET : end]
    (digest,) = struct.unpack(">I", digest_bytes)
    if strict and checksum(head + body) != digest:
        raise ChecksumMismatchError(f"checksum mismatch at offset {offset}")
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TornFrameError(f"payload is not canonical JSON at offset {offset}: {exc}") from exc
    return Frame(kind=FrameKind(kind_value), payload=payload, offset=offset, size=end - offset)


def iter_frames(data: bytes, *, strict: bool = True):
    """Yield frames from a byte buffer, stopping cleanly at the first torn frame."""

    offset = 0
    while offset < len(data):
        frame = decode(data, offset=offset, strict=strict)
        yield frame
        offset += frame.size


def describe(frame: Frame) -> str:
    return f"{frame.kind.name}@{frame.offset}+{frame.size}"
