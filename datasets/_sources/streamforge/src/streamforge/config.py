"""Validated window definitions and canonical pipeline fingerprints."""

import hashlib
import json
from dataclasses import asdict, dataclass

from .model import integer


@dataclass(frozen=True)
class Window:
    name: str
    kind: str
    size: int = 0
    step: int = 0
    gap: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("window name is required")
        for name in ("size", "step", "gap"):
            if integer(getattr(self, name), name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.kind == "fixed":
            valid = self.size > 0 and self.step == self.gap == 0
        elif self.kind == "sliding":
            valid = self.size > 0 and 0 < self.step <= self.size and self.gap == 0
        elif self.kind == "session":
            valid = self.gap > 0 and self.size == self.step == 0
        else:
            valid = False
        if not valid:
            raise ValueError("invalid window definition")


@dataclass(frozen=True)
class Pipeline:
    partitions: tuple[str, ...]
    windows: tuple[Window, ...]
    lateness: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "partitions", tuple(self.partitions))
        object.__setattr__(self, "windows", tuple(self.windows))
        if (
            not self.partitions
            or any(not isinstance(name, str) or not name for name in self.partitions)
            or len(set(self.partitions)) != len(self.partitions)
        ):
            raise ValueError("partitions must be distinct nonempty names")
        if not self.windows or any(not isinstance(item, Window) for item in self.windows):
            raise ValueError("at least one window is required")
        if len({item.name for item in self.windows}) != len(self.windows):
            raise ValueError("window names must be distinct")
        if integer(self.lateness, "lateness") < 0:
            raise ValueError("lateness must be nonnegative")

    def document(self) -> dict:
        return {
            "partitions": sorted(self.partitions),
            "windows": sorted((asdict(item) for item in self.windows), key=lambda row: row["name"]),
            "lateness": self.lateness,
        }

    @property
    def fingerprint(self) -> str:
        data = json.dumps(self.document(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(data).hexdigest()
