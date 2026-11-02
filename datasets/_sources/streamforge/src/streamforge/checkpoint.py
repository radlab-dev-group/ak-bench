"""Atomic, checksummed checkpoint envelopes with configuration binding."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .errors import InvalidCheckpoint


def canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def save(path: Path, fingerprint: str, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": 1, "pipeline": fingerprint, "state": state}
    envelope = {"body": body, "sha256": hashlib.sha256(canonical(body)).hexdigest()}
    descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(envelope))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path: Path, fingerprint: str) -> dict:
    try:
        envelope = json.loads(Path(path).read_bytes())
        body = envelope["body"]
        if hashlib.sha256(canonical(body)).hexdigest() != envelope["sha256"]:
            raise ValueError("checksum mismatch")
        if body["version"] != 1 or body["pipeline"] != fingerprint:
            raise ValueError("checkpoint version or pipeline mismatch")
        if not isinstance(body["state"], dict):
            raise ValueError("invalid checkpoint state")
        return body["state"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise InvalidCheckpoint(str(error)) from error
