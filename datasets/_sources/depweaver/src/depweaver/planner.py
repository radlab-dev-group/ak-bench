"""Deterministic environment transition plans and atomic in-memory application."""

import hashlib
from dataclasses import dataclass

from .graph import Graph
from .model import Release, Resolution, canonical


@dataclass(frozen=True)
class Installed:
    packages: tuple[Release, ...] = ()

    def __post_init__(self) -> None:
        names = [release.name for release in self.packages]
        if names != sorted(names) or len(set(names)) != len(names):
            raise ValueError("installed packages must have distinct sorted names")

    def document(self) -> dict:
        return {"packages": [release.document() for release in self.packages]}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical(self.document()).encode()).hexdigest()

    @classmethod
    def load(cls, document: dict) -> "Installed":
        if set(document) != {"packages"} or not isinstance(document["packages"], list):
            raise ValueError("invalid installed environment")
        return cls(tuple(Release.load(row) for row in document["packages"]))


@dataclass(frozen=True)
class Operation:
    kind: str
    name: str
    before: Release | None
    after: Release | None

    def inverse(self) -> "Operation":
        return Operation(
            "remove"
            if self.kind == "install"
            else "install"
            if self.kind == "remove"
            else "replace",
            self.name,
            self.after,
            self.before,
        )

    def document(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "before": self.before.document() if self.before else None,
            "after": self.after.document() if self.after else None,
        }


@dataclass(frozen=True)
class Plan:
    base: str
    target: str
    operations: tuple[Operation, ...]
    groups: tuple[tuple[str, ...], ...]

    def apply(self, installed: Installed) -> Installed:
        if installed.fingerprint != self.base:
            raise ValueError("environment changed since plan creation")
        candidate = {release.name: release for release in installed.packages}
        for operation in self.operations:
            if candidate.get(operation.name) != operation.before:
                raise ValueError("operation precondition failed")
            if operation.after is None:
                candidate.pop(operation.name)
            else:
                if operation.after.name != operation.name:
                    raise ValueError("operation changes package identity")
                candidate[operation.name] = operation.after
        result = Installed(tuple(candidate[name] for name in sorted(candidate)))
        if result.fingerprint != self.target:
            raise ValueError("plan target fingerprint mismatch")
        return result

    def inverse(self) -> "Plan":
        return Plan(
            self.target,
            self.base,
            tuple(operation.inverse() for operation in reversed(self.operations)),
            tuple(reversed(self.groups)),
        )

    def document(self) -> dict:
        return {
            "version": 1,
            "base": self.base,
            "target": self.target,
            "operations": [operation.document() for operation in self.operations],
            "groups": [list(group) for group in self.groups],
        }

    @classmethod
    def load(cls, document: dict) -> "Plan":
        if document.get("version") != 1:
            raise ValueError("unsupported plan version")
        operations = []
        for row in document["operations"]:
            before = Release.load(row["before"]) if row["before"] is not None else None
            after = Release.load(row["after"]) if row["after"] is not None else None
            kind = row["kind"]
            if kind not in {"install", "remove", "replace"}:
                raise ValueError("invalid plan operation")
            if kind == "install" and (before is not None or after is None):
                raise ValueError("invalid install pre/postcondition")
            if kind == "remove" and (before is None or after is not None):
                raise ValueError("invalid remove pre/postcondition")
            if kind == "replace" and (before is None or after is None):
                raise ValueError("invalid replace pre/postcondition")
            operations.append(Operation(kind, row["name"], before, after))
        return cls(
            document["base"],
            document["target"],
            tuple(operations),
            tuple(tuple(group) for group in document["groups"]),
        )


def plan(installed: Installed, resolution: Resolution) -> Plan:
    before = {release.name: release for release in installed.packages}
    after = {release.name: release for release in resolution.selected}
    graph = Graph.from_resolution(resolution)
    operations = []
    for name in sorted(before.keys() - after.keys(), reverse=True):
        operations.append(Operation("remove", name, before[name], None))
    groups = tuple(group for layer in graph.layers() for group in layer)
    for group in groups:
        for name in group:
            if name not in before:
                operations.append(Operation("install", name, None, after[name]))
            elif before[name] != after[name]:
                operations.append(Operation("replace", name, before[name], after[name]))
    target = Installed(tuple(after[name] for name in sorted(after)))
    return Plan(installed.fingerprint, target.fingerprint, tuple(operations), groups)
