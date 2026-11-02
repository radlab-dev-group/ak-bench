"""Incremental source catalog and deterministic dependency invalidation."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import ast
from .diagnostics import CompileError
from .parser import parse_module
from .project import Build, build, dependency_order


@dataclass(frozen=True)
class File:
    name: str
    text: str
    digest: str
    syntax: ast.Module


@dataclass(frozen=True)
class ChangeSet:
    changed: tuple[str, ...]
    removed: tuple[str, ...]
    affected: tuple[str, ...]


class Workspace:
    def __init__(self) -> None:
        self.files: dict[str, File] = {}
        self.revision = 0
        self.last_build: Build | None = None

    def update(self, sources: dict[str, str], *, replace_all: bool = False) -> ChangeSet:
        candidate = self.files.copy()
        changed, removed = [], []
        if replace_all:
            for name in sorted(candidate.keys() - sources.keys()):
                removed.append(candidate.pop(name).syntax.name)
        for name, text in sorted(sources.items()):
            digest = hashlib.sha256(text.encode()).hexdigest()
            previous = candidate.get(name)
            if previous is not None and previous.digest == digest:
                continue
            syntax = parse_module(text, name)
            candidate[name] = File(name, text, digest, syntax)
            changed.append(syntax.name)
            if previous and previous.syntax.name != syntax.name:
                removed.append(previous.syntax.name)
        modules = {}
        for file in candidate.values():
            if file.syntax.name in modules:
                raise CompileError("duplicate-module", "duplicate module", file.syntax.span)
            modules[file.syntax.name] = file.syntax
        dependency_order(modules)
        reverse = {name: set() for name in modules}
        for module in modules.values():
            for imported in module.imports:
                reverse[imported.module].add(module.name)
        affected = set(changed) | set(removed)
        pending = list(affected)
        while pending:
            name = pending.pop()
            for dependent in reverse.get(name, ()):
                if dependent not in affected:
                    affected.add(dependent)
                    pending.append(dependent)
        if changed or removed:
            self.files = candidate
            self.revision += 1
            self.last_build = None
        return ChangeSet(tuple(sorted(changed)), tuple(sorted(removed)), tuple(sorted(affected)))

    def check(self) -> Build:
        if self.last_build is None:
            self.last_build = build({name: file.text for name, file in self.files.items()})
        return self.last_build

    def document(self) -> dict:
        return {
            "version": 1,
            "revision": self.revision,
            "files": [
                {"name": file.name, "text": file.text, "digest": file.digest}
                for name, file in sorted(self.files.items())
            ],
        }

    @classmethod
    def load(cls, document: dict) -> "Workspace":
        if (
            document.get("version") != 1
            or type(document.get("revision")) is not int
            or document["revision"] < 0
        ):
            raise ValueError("invalid workspace version or revision")
        workspace = cls()
        sources = {}
        for file in document["files"]:
            if (
                file["name"] in sources
                or hashlib.sha256(file["text"].encode()).hexdigest() != file["digest"]
            ):
                raise ValueError("duplicate workspace file or checksum mismatch")
            sources[file["name"]] = file["text"]
        workspace.update(sources)
        workspace.revision = document["revision"]
        return workspace

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.document(), sort_keys=True, indent=2) + "\n")


def discover(root: Path) -> dict[str, str]:
    root = Path(root).resolve()
    sources = {}
    for path in sorted(root.rglob("*.tw")):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("source symlink escapes workspace")
        sources[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
    return sources
