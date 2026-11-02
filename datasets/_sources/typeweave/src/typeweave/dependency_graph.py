"""Module impact analysis and source/interface dependency fingerprints."""

import hashlib
import json
from dataclasses import dataclass

from . import ast
from .project import dependency_order


@dataclass(frozen=True)
class Graph:
    modules: tuple[ast.Module, ...]

    def __post_init__(self) -> None:
        if len({module.name for module in self.modules}) != len(self.modules):
            raise ValueError("duplicate module graph node")
        dependency_order({module.name: module for module in self.modules})

    @property
    def forward(self) -> dict[str, tuple[str, ...]]:
        return {
            module.name: tuple(sorted({item.module for item in module.imports}))
            for module in self.modules
        }

    @property
    def reverse(self) -> dict[str, tuple[str, ...]]:
        result = {module.name: set() for module in self.modules}
        for parent, imports in self.forward.items():
            for dependency in imports:
                result[dependency].add(parent)
        return {name: tuple(sorted(values)) for name, values in result.items()}

    def closure(self, names: tuple[str, ...], *, dependents: bool = False) -> tuple[str, ...]:
        edges = self.reverse if dependents else self.forward
        pending, visited = list(names), set()
        while pending:
            name = pending.pop()
            if name not in edges:
                raise KeyError(name)
            if name not in visited:
                visited.add(name)
                pending.extend(edges[name])
        return tuple(sorted(visited))

    def levels(self) -> tuple[tuple[str, ...], ...]:
        forward = self.forward
        remaining, done, result = set(forward), set(), []
        while remaining:
            ready = tuple(sorted(name for name in remaining if set(forward[name]) <= done))
            if not ready:
                raise ValueError("cycle in module graph")
            result.append(ready)
            remaining.difference_update(ready)
            done.update(ready)
        return tuple(result)

    def fingerprint(self, name: str, content_hashes: dict[str, str]) -> str:
        closure = self.closure((name,))
        document = {
            module: {"content": content_hashes[module], "imports": self.forward[module]}
            for module in closure
        }
        return hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def document(self) -> dict:
        return {
            "version": 1,
            "imports": self.forward,
            "levels": [list(level) for level in self.levels()],
        }

    def dot(self) -> str:
        lines = ["digraph typeweave {"]
        for module in sorted(self.forward):
            lines.append("  " + json.dumps(module) + ";")
            for dependency in self.forward[module]:
                lines.append("  " + json.dumps(module) + " -> " + json.dumps(dependency) + ";")
        return "\n".join(lines) + "\n}\n"
