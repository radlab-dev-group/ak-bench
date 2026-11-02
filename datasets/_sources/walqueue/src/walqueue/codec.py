"""Length-prefixed canonical JSON frames protected by SHA-256."""

import hashlib
import json
import struct
from dataclasses import dataclass

from .errors import CorruptStore

HEADER = struct.Struct(">I")
DIGEST_SIZE = 32
MAX_PAYLOAD = 1_048_576


def canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def encode(document: dict) -> bytes:
    payload = canonical(document)
    if not payload or len(payload) > MAX_PAYLOAD:
        raise ValueError("frame payload is too large")
    return HEADER.pack(len(payload)) + payload + hashlib.sha256(payload).digest()


@dataclass(frozen=True)
class Decoded:
    documents: tuple[dict, ...]
    valid_bytes: int
    torn: bool


def decode(data: bytes, *, allow_torn_tail: bool) -> Decoded:
    cursor = 0
    documents = []
    while cursor < len(data):
        start = cursor
        if len(data) - cursor < HEADER.size:
            if allow_torn_tail:
                return Decoded(tuple(documents), start, True)
            raise CorruptStore("incomplete frame header in sealed segment")
        length = HEADER.unpack_from(data, cursor)[0]
        if not 0 < length <= MAX_PAYLOAD:
            raise CorruptStore("invalid frame length")
        cursor += HEADER.size
        finish = cursor + length + DIGEST_SIZE
        if finish > len(data):
            if allow_torn_tail:
                return Decoded(tuple(documents), start, True)
            raise CorruptStore("incomplete frame in sealed segment")
        payload = data[cursor : cursor + length]
        digest = data[cursor + length : finish]
        if hashlib.sha256(payload).digest() != digest:
            raise CorruptStore("frame checksum mismatch")
        try:
            document = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise CorruptStore("invalid frame JSON") from error
        if not isinstance(document, dict):
            raise CorruptStore("frame must contain an object")
        documents.append(document)
        cursor = finish
    return Decoded(tuple(documents), cursor, False)
