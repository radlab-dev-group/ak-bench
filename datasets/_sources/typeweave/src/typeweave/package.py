"""Portable source packages, dependency impact and incremental build orchestration."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .artifacts import Store, atomic_write, canonical, digest
from .compiler import Compilation, project
from .dependency_graph import Graph
from .parser import parse_module
from .validation import validate


def relative_name(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("invalid source path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("source paths must be normalized and relative")
    if path.as_posix() != value or path.suffix != ".tw":
        raise ValueError("source path must be a canonical .tw path")
    return value


@dataclass(frozen=True)
class Unit:
    path: str
    text: str

    def __post_init__(self) -> None:
        relative_name(self.path)
        if not isinstance(self.text, str):
            raise ValueError("source text must be a string")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    def document(self) -> dict:
        return {"path": self.path, "text": self.text, "sha256": self.digest}


@dataclass(frozen=True)
class Difference:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]
    affected: tuple[str, ...]

    def document(self) -> dict:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "modified": list(self.modified),
            "affected": list(self.affected),
        }


class Package:
    def __init__(self, name: str, units: tuple[Unit, ...]) -> None:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
            raise ValueError("invalid source package name")
        paths = [unit.path for unit in units]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate source path")
        if len({path.casefold() for path in paths}) != len(paths):
            raise ValueError("source paths collide on case insensitive filesystems")
        modules, owners = {}, {}
        for unit in sorted(units, key=lambda item: item.path):
            module = parse_module(unit.text, unit.path)
            validate(module)
            if module.name in modules:
                raise ValueError("duplicate source module: " + module.name)
            modules[module.name], owners[module.name] = module, unit.path
        self.graph = Graph(tuple(modules.values()))
        self.name = name
        self.units = tuple(sorted(units, key=lambda item: item.path))
        self.modules = modules
        self.owners = owners

    @property
    def sources(self) -> dict[str, str]:
        return {unit.path: unit.text for unit in self.units}

    @property
    def module_hashes(self) -> dict[str, str]:
        hashes = {unit.path: unit.digest for unit in self.units}
        return {module: hashes[path] for module, path in self.owners.items()}

    @property
    def fingerprint(self) -> str:
        return digest(self.document())

    def document(self) -> dict:
        return {
            "version": 1,
            "name": self.name,
            "sources": [unit.document() for unit in self.units],
        }

    @classmethod
    def load(cls, document: dict) -> "Package":
        if not isinstance(document, dict) or set(document) != {"version", "name", "sources"}:
            raise ValueError("invalid source package fields")
        if document["version"] != 1 or not isinstance(document["sources"], list):
            raise ValueError("invalid source package version/sources")
        units = []
        for row in document["sources"]:
            if not isinstance(row, dict) or set(row) != {"path", "text", "sha256"}:
                raise ValueError("invalid source unit fields")
            unit = Unit(row["path"], row["text"])
            if unit.digest != row["sha256"]:
                raise ValueError("source checksum mismatch")
            units.append(unit)
        if [unit.path for unit in units] != sorted(unit.path for unit in units):
            raise ValueError("source package paths must be sorted")
        return cls(document["name"], tuple(units))

    @classmethod
    def read(cls, path: Path) -> "Package":
        return cls.load(json.loads(Path(path).read_text(encoding="utf-8")))

    def write(self, path: Path) -> None:
        atomic_write(Path(path), canonical(self.document()))

    @classmethod
    def discover(
        cls, root: Path, name: str = "Sources", *, max_bytes: int = 10_000_000
    ) -> "Package":
        root = Path(root).resolve(strict=True)
        if not root.is_dir() or type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("invalid source directory or byte limit")
        units, consumed = [], 0
        for path in sorted(root.rglob("*.tw")):
            if not path.is_file():
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ValueError("source symlink escapes package root")
            raw = path.read_bytes()
            consumed += len(raw)
            if consumed > max_bytes:
                raise ValueError("source package exceeds byte limit")
            units.append(Unit(path.relative_to(root).as_posix(), raw.decode("utf-8")))
        return cls(name, tuple(units))

    def materialize(self, root: Path, *, overwrite: bool = False) -> tuple[Path, ...]:
        root = Path(root).resolve()
        paths = []
        for unit in self.units:
            path = root / unit.path
            if not path.resolve().is_relative_to(root):
                raise ValueError("destination symlink escapes package root")
            if path.exists() and not overwrite:
                raise FileExistsError(path)
            paths.append(path)
        for unit, path in zip(self.units, paths, strict=True):
            atomic_write(path, unit.text.encode())
        return tuple(paths)

    def compare(self, other: "Package") -> Difference:
        before, after = self.sources, other.sources
        added, removed = after.keys() - before.keys(), before.keys() - after.keys()
        modified = {name for name in before.keys() & after.keys() if before[name] != after[name]}
        changed = set(added) | set(removed) | modified
        affected = set()
        for package in (self, other):
            modules = tuple(name for name, path in package.owners.items() if path in changed)
            affected.update(package.graph.closure(modules, dependents=True))
        return Difference(
            tuple(sorted(added)),
            tuple(sorted(removed)),
            tuple(sorted(modified)),
            tuple(sorted(affected)),
        )

    def compile(self, store: Store | None = None) -> Compilation:
        return project(self.sources, store)

    def plan(self, store: Store) -> dict:
        """Predict conservative source-triggered invalidation without checking types."""
        changed = []
        for module, fingerprint in sorted(self.module_hashes.items()):
            previous = store.read(module)
            if previous is None or previous.source_digest != fingerprint:
                changed.append(module)
        affected = self.graph.closure(tuple(changed), dependents=True)
        stale = tuple(name for name, fingerprint in store.inventory() if name not in self.modules)
        return {
            "package": self.fingerprint,
            "changed": changed,
            "affected": list(affected),
            "removed": list(stale),
            "levels": [list(level) for level in self.graph.levels()],
        }

    def report(self) -> dict:
        from .analysis import module_dependencies, statistics

        return {
            "name": self.name,
            "fingerprint": self.fingerprint,
            "units": [
                {"path": unit.path, "bytes": len(unit.text.encode()), "sha256": unit.digest}
                for unit in self.units
            ],
            "modules": {
                name: {
                    "path": self.owners[name],
                    "definitions": len(module.definitions),
                    "dependencies": module_dependencies(module),
                    "statistics": {
                        binding.name: statistics(binding.value) for binding in module.definitions
                    },
                }
                for name, module in sorted(self.modules.items())
            },
            "graph": self.graph.document(),
        }
