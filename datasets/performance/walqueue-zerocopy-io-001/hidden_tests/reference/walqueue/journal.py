"""Segmented transaction journal. A complete frame is one atomic transaction."""

import os
import re
from collections.abc import Callable
from pathlib import Path

from .codec import HEADER, decode, encode
from .errors import CorruptStore
from .files import sync_directory
from .model import integer

SEGMENT = re.compile(r"wal-(\d{16})\.log\Z")


class Journal:
    def __init__(self, root: Path, hook: Callable[[str], None]) -> None:
        self.root = root
        self.hook = hook
        self.paths = self._discover()
        if not self.paths:
            self.paths = [self._create(1)]

    def _discover(self) -> list[Path]:
        paths = []
        for path in self.root.glob("wal-*.log"):
            if not SEGMENT.fullmatch(path.name):
                raise CorruptStore("malformed segment filename")
            paths.append(path)
        return sorted(paths)

    def _create(self, number: int) -> Path:
        path = self.root / f"wal-{number:016d}.log"
        with path.open("xb") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(self.root)
        return path

    @property
    def active(self) -> Path:
        return self.paths[-1]

    def append(self, sequence: int, commands: list[dict]) -> None:
        frame = encode({"sequence": sequence, "commands": commands})
        length = HEADER.unpack_from(frame)[0]
        with self.active.open("ab", buffering=0) as stream:
            stream.write(frame[: HEADER.size])
            self.hook("append.header")
            stream.write(frame[HEADER.size : HEADER.size + length])
            self.hook("append.payload")
            stream.write(frame[HEADER.size + length :])
            self.hook("append.frame")
            os.fsync(stream.fileno())
            self.hook("append.synced")

    def recover(self, through: int) -> list[dict]:
        integer(through, "snapshot sequence")
        recovered = []
        previous = None
        expected = through + 1
        for position, path in enumerate(self.paths):
            decoded = decode(path.read_bytes(), allow_torn_tail=position == len(self.paths) - 1)
            for document in decoded.documents:
                try:
                    sequence = integer(document["sequence"], "transaction sequence", 1)
                    commands = document["commands"]
                    if not isinstance(commands, list) or not commands:
                        raise ValueError("empty transaction")
                    if previous is not None and sequence != previous + 1:
                        raise ValueError("journal sequence is not contiguous")
                    previous = sequence
                    if sequence <= through:
                        continue
                    if sequence != expected:
                        raise ValueError("journal has a gap after snapshot")
                    recovered.append(document)
                    expected += 1
                except (KeyError, TypeError, ValueError) as error:
                    raise CorruptStore("invalid transaction sequence or shape") from error
            if decoded.torn:
                with path.open("r+b") as stream:
                    stream.truncate(decoded.valid_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
        return recovered

    def rotate(self) -> None:
        number = int(SEGMENT.fullmatch(self.active.name)[1]) + 1
        self.paths.append(self._create(number))

    def discard_sealed(self) -> None:
        for path in self.paths[:-1]:
            path.unlink()
        self.paths = [self.active]
        sync_directory(self.root)
