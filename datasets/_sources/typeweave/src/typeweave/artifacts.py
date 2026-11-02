"""Checksummed compiler artifacts with atomic publication and dependency binding."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .bytecode import Code
from .interfaces import Interface


def canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(document: object) -> str:
    return hashlib.sha256(canonical(document)).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".typeweave-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
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


@dataclass(frozen=True)
class Artifact:
    source_digest: str
    interface: Interface
    dependencies: tuple[tuple[str, str], ...]
    definitions: tuple[tuple[str, Code], ...]

    def document(self) -> dict:
        body = {
            "version": 1,
            "source": self.source_digest,
            "interface": self.interface.document(),
            "dependencies": dict(self.dependencies),
            "definitions": {name: code.document() for name, code in self.definitions},
        }
        return {"body": body, "digest": digest(body)}

    @classmethod
    def load(cls, document: dict) -> "Artifact":
        if not isinstance(document, dict) or set(document) != {"body", "digest"}:
            raise ValueError("invalid artifact envelope")
        body = document["body"]
        if digest(body) != document["digest"] or body.get("version") != 1:
            raise ValueError("artifact checksum/version mismatch")
        source_digest = body["source"]
        if (
            not isinstance(source_digest, str)
            or len(source_digest) != 64
            or any(character not in "0123456789abcdef" for character in source_digest)
        ):
            raise ValueError("invalid source fingerprint")
        interface = Interface.load(body["interface"])
        dependencies = tuple(sorted(body["dependencies"].items()))
        for name, fingerprint in dependencies:
            if (
                not isinstance(name, str)
                or not isinstance(fingerprint, str)
                or len(fingerprint) != 64
            ):
                raise ValueError("invalid dependency fingerprint")
        definitions = tuple(
            (name, Code.load(code)) for name, code in sorted(body["definitions"].items())
        )
        if not set(interface.document()["values"]) <= {name for name, code in definitions} | set(
            interface.document()["constructors"]
        ):
            raise ValueError("artifact omits a public definition")
        return cls(source_digest, interface, dependencies, definitions)

    def valid_for(self, source: str, imports: dict[str, Interface]) -> bool:
        if hashlib.sha256(source.encode()).hexdigest() != self.source_digest:
            return False
        actual = tuple(
            sorted((name, digest(interface.document())) for name, interface in imports.items())
        )
        return actual == self.dependencies


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, module: str) -> Path:
        if not module or any(not (character.isalnum() or character == "_") for character in module):
            raise ValueError("invalid artifact module name")
        return self.root / (module + ".json")

    def publish(self, artifact: Artifact) -> None:
        atomic_write(self.path(artifact.interface.module), canonical(artifact.document()))

    def read(self, module: str) -> Artifact | None:
        path = self.path(module)
        if not path.exists():
            return None
        artifact = Artifact.load(json.loads(path.read_bytes()))
        if artifact.interface.module != module:
            raise ValueError("artifact module name mismatch")
        return artifact

    def invalidate(self, modules: tuple[str, ...]) -> tuple[str, ...]:
        removed = []
        for module in sorted(set(modules)):
            path = self.path(module)
            if path.exists():
                path.unlink()
                removed.append(module)
        return tuple(removed)

    def inventory(self) -> tuple[tuple[str, str], ...]:
        if not self.root.exists():
            return ()
        entries = []
        for path in sorted(self.root.glob("*.json")):
            artifact = self.read(path.stem)
            entries.append((artifact.interface.module, digest(artifact.document())))
        return tuple(entries)
