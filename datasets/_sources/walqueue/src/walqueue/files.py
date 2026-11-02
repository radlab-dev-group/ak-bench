"""Durable file replacement, directory sync, and checksum envelopes."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .codec import canonical
from .errors import CorruptStore


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def replace_bytes(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_document(path: Path, document: dict) -> None:
    checksum = hashlib.sha256(canonical(document)).hexdigest()
    replace_bytes(path, canonical({"document": document, "sha256": checksum}))


def read_document(path: Path) -> dict:
    try:
        envelope = json.loads(path.read_bytes())
        document = envelope["document"]
        if not isinstance(document, dict):
            raise ValueError("envelope document must be an object")
        if hashlib.sha256(canonical(document)).hexdigest() != envelope["sha256"]:
            raise ValueError("envelope checksum mismatch")
        return document
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise CorruptStore(f"invalid envelope: {path.name}") from error
