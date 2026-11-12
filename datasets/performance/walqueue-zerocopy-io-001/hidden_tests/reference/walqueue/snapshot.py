"""CURRENT is the publication point; orphan snapshot files are never authoritative."""

import re
from collections.abc import Callable
from pathlib import Path

from .errors import CorruptStore
from .files import read_document, write_document
from .model import integer
from .state import State

SNAPSHOT = re.compile(r"snapshot-(\d{16})\.json\Z")


class Snapshots:
    def __init__(self, root: Path, hook: Callable[[str], None]) -> None:
        self.root = root
        self.hook = hook

    def load(self) -> tuple[int, State]:
        current = self.root / "CURRENT"
        if not current.exists():
            return 0, State()
        pointer = read_document(current)
        try:
            filename = pointer["snapshot"]
            if not isinstance(filename, str) or not SNAPSHOT.fullmatch(filename):
                raise ValueError("invalid snapshot filename")
            through = integer(pointer["through"], "snapshot sequence")
            if int(SNAPSHOT.fullmatch(filename)[1]) != through:
                raise ValueError("snapshot filename/sequence mismatch")
            document = read_document(self.root / filename)
            if document["version"] != 1 or document["through"] != through:
                raise ValueError("snapshot/pointer mismatch")
            return through, State.restore(document["state"])
        except (KeyError, TypeError, ValueError) as error:
            raise CorruptStore("invalid snapshot pointer") from error

    def publish(self, through: int, state: State) -> None:
        filename = f"snapshot-{through:016d}.json"
        write_document(
            self.root / filename,
            {
                "version": 1,
                "through": through,
                "state": state.document(),
            },
        )
        self.hook("compact.snapshot")
        write_document(self.root / "CURRENT", {"snapshot": filename, "through": through})
        self.hook("compact.manifest")
