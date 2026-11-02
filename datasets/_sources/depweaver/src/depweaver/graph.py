"""Resolved dependency graph with cycles, reverse impact and installation groups."""

from collections import deque
from dataclasses import dataclass

from .model import Resolution


@dataclass(frozen=True, order=True)
class Edge:
    parent: str
    child: str
    requirement: str
    marker: str
    extras: tuple[str, ...]


class Graph:
    def __init__(self, names: tuple[str, ...], edges: tuple[Edge, ...]) -> None:
        self.names = tuple(sorted(set(names)))
        self.edges = tuple(sorted(set(edges)))
        if any(
            edge.parent not in self.names or edge.child not in self.names for edge in self.edges
        ):
            raise ValueError("graph edge references an absent package")
        self.forward = {name: set() for name in self.names}
        self.reverse = {name: set() for name in self.names}
        for edge in self.edges:
            self.forward[edge.parent].add(edge.child)
            self.reverse[edge.child].add(edge.parent)

    @classmethod
    def from_resolution(cls, resolution: Resolution) -> "Graph":
        extras = dict(resolution.extras)
        selected = {release.name: release for release in resolution.selected}
        edges = []
        for release in resolution.selected:
            for dependency in release.dependencies:
                if dependency.marker.matches(
                    resolution.target, frozenset(extras.get(release.name, ()))
                ):
                    if dependency.name not in selected:
                        raise ValueError("resolution misses an active dependency")
                    if not dependency.spec.matches(selected[dependency.name].version):
                        raise ValueError("resolution violates an edge requirement")
                    edges.append(
                        Edge(
                            release.name,
                            dependency.name,
                            str(dependency.spec),
                            dependency.marker.text,
                            tuple(sorted(dependency.extras)),
                        )
                    )
        return cls(tuple(selected), tuple(edges))

    def reachable(self, roots: tuple[str, ...], *, reverse: bool = False) -> tuple[str, ...]:
        edges = self.reverse if reverse else self.forward
        pending, visited = deque(roots), set()
        while pending:
            name = pending.popleft()
            if name not in edges:
                raise KeyError(name)
            if name in visited:
                continue
            visited.add(name)
            pending.extend(sorted(edges[name] - visited))
        return tuple(sorted(visited))

    def shortest_path(self, start: str, finish: str) -> tuple[str, ...] | None:
        if start not in self.forward or finish not in self.forward:
            raise KeyError("unknown graph node")
        pending = deque([(start,)])
        visited = {start}
        while pending:
            path = pending.popleft()
            if path[-1] == finish:
                return path
            for child in sorted(self.forward[path[-1]]):
                if child not in visited:
                    visited.add(child)
                    pending.append((*path, child))
        return None

    def components(self) -> tuple[tuple[str, ...], ...]:
        indices, lowlinks = {}, {}
        stack, active, result = [], set(), []
        counter = 0

        def visit(name):
            nonlocal counter
            indices[name] = lowlinks[name] = counter
            counter += 1
            stack.append(name)
            active.add(name)
            for child in sorted(self.forward[name]):
                if child not in indices:
                    visit(child)
                    lowlinks[name] = min(lowlinks[name], lowlinks[child])
                elif child in active:
                    lowlinks[name] = min(lowlinks[name], indices[child])
            if indices[name] == lowlinks[name]:
                component = []
                while True:
                    member = stack.pop()
                    active.remove(member)
                    component.append(member)
                    if member == name:
                        break
                result.append(tuple(sorted(component)))

        for name in self.names:
            if name not in indices:
                visit(name)
        return tuple(result)

    def layers(self) -> tuple[tuple[tuple[str, ...], ...], ...]:
        components = self.components()
        owner = {name: index for index, group in enumerate(components) for name in group}
        dependencies = {index: set() for index in range(len(components))}
        for edge in self.edges:
            if owner[edge.parent] != owner[edge.child]:
                dependencies[owner[edge.parent]].add(owner[edge.child])
        completed, layers = set(), []
        while len(completed) != len(components):
            ready = [
                index
                for index, needed in dependencies.items()
                if index not in completed and needed <= completed
            ]
            if not ready:
                raise ValueError("invalid condensed graph")
            layers.append(tuple(sorted(components[index] for index in ready)))
            completed.update(ready)
        return tuple(layers)

    def document(self) -> dict:
        return {
            "nodes": list(self.names),
            "edges": [
                {
                    "parent": edge.parent,
                    "child": edge.child,
                    "requirement": edge.requirement,
                    "marker": edge.marker,
                    "extras": list(edge.extras),
                }
                for edge in self.edges
            ],
            "layers": [[list(group) for group in layer] for layer in self.layers()],
        }

    def dot(self) -> str:
        import json

        lines = ["digraph dependencies {"]
        for name in self.names:
            lines.append("  " + json.dumps(name) + ";")
        for edge in self.edges:
            lines.append("  " + json.dumps(edge.parent) + " -> " + json.dumps(edge.child) + ";")
        return "\n".join(lines) + "\n}\n"
