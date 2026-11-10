"""Content-addressed offline artifact storage with verified immutable publication.

Besides artifact blobs and indexes the store keeps cached resolutions: a
manifest's lockfile together with its proof of solution. A cached resolution
is only ever handed back after its proof verifies under the catalog the caller
is using now; one that no longer verifies is removed, never returned.
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .codec import envelope, read, unwrap, write
from .codec import request as load_request
from .lockfile import Lockfile
from .model import Request
from .proofs import Proof, ProofInvalid, verify_proof
from .repository import Repository
from .wheels import ArchiveReport, inspect

RESOLUTION_KIND = "cached-resolution"


def fingerprint(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("invalid SHA-256 fingerprint")
    return value


@dataclass(frozen=True)
class Entry:
    digest: str
    size: int
    filename: str

    def __post_init__(self) -> None:
        fingerprint(self.digest)
        if type(self.size) is not int or self.size < 0:
            raise ValueError("invalid artifact size")
        if (
            not isinstance(self.filename, str)
            or Path(self.filename).name != self.filename
            or self.filename in {"", ".", ".."}
            or "\\" in self.filename
        ):
            raise ValueError("invalid artifact filename")

    def document(self) -> dict:
        return {"digest": self.digest, "size": self.size, "filename": self.filename}


@dataclass(frozen=True)
class Index:
    entries: tuple[Entry, ...]

    def __post_init__(self) -> None:
        names = [entry.filename for entry in self.entries]
        if names != sorted(set(names)):
            raise ValueError("artifact index filenames must be distinct and sorted")

    def document(self) -> dict:
        return envelope("artifact-index", [entry.document() for entry in self.entries])

    @classmethod
    def load(cls, document: dict) -> "Index":
        payload = unwrap(document, "artifact-index")
        if not isinstance(payload, list):
            raise ValueError("invalid artifact index")
        return cls(tuple(Entry(**row) for row in payload))

    def merge(self, other: "Index") -> "Index":
        entries = {entry.filename: entry for entry in self.entries}
        for entry in other.entries:
            if entry.filename in entries and entries[entry.filename] != entry:
                raise ValueError("artifact index name collision")
            entries[entry.filename] = entry
        return Index(tuple(entries[name] for name in sorted(entries)))


class Store:
    def __init__(self, root: Path, *, max_bytes: int = 100_000_000) -> None:
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("invalid artifact byte limit")
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes

    def path(self, digest: str) -> Path:
        digest = fingerprint(digest)
        path = self.root / "objects" / digest[:2] / digest[2:]
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("artifact store symlink escapes root")
        return path

    def put(self, data: bytes, filename: str, *, expected: str | None = None) -> Entry:
        if not isinstance(data, bytes) or len(data) > self.max_bytes:
            raise ValueError("invalid or oversized artifact")
        digest = hashlib.sha256(data).hexdigest()
        entry = Entry(digest, len(data), filename)
        if expected is not None and fingerprint(expected) != digest:
            raise ValueError("artifact does not match expected digest")
        path = self.path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.get(entry)
            return entry
        descriptor, temporary = tempfile.mkstemp(prefix=".artifact-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                self.get(entry)
        finally:
            os.unlink(temporary)
        return entry

    def get(self, entry: Entry) -> bytes:
        path = self.path(entry.digest)
        if path.stat().st_size != entry.size or entry.size > self.max_bytes:
            raise ValueError("stored artifact size mismatch")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.digest:
            raise ValueError("stored artifact checksum mismatch")
        return data

    def import_file(self, path: Path, *, expected: str | None = None) -> Entry:
        path = Path(path)
        if path.stat().st_size > self.max_bytes:
            raise ValueError("artifact exceeds byte limit")
        return self.put(path.read_bytes(), path.name, expected=expected)

    def export(self, entry: Entry, destination: Path, *, overwrite: bool = False) -> Path:
        data = self.get(entry)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / entry.filename
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError("export symlink escapes destination")
        mode = "wb" if overwrite else "xb"
        with path.open(mode) as stream:
            stream.write(data)
        return path

    def verify_wheel(self, entry: Entry) -> ArchiveReport:
        data = self.get(entry)
        with tempfile.TemporaryDirectory(prefix="depweaver-wheel-") as temporary:
            path = Path(temporary) / entry.filename
            path.write_bytes(data)
            return inspect(path, expected_digest=entry.digest, max_bytes=self.max_bytes)

    def publish(self, name: str, index: Index) -> None:
        path = self.index_path(name)
        for entry in index.entries:
            self.get(entry)
        write(path, index.document())

    def index_path(self, name: str) -> Path:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("invalid artifact index name")
        path = self.root / "indexes" / (name + ".json")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("index symlink escapes store root")
        return path

    def index(self, name: str) -> Index:
        result = Index.load(read(self.index_path(name)))
        for entry in result.entries:
            self.get(entry)
        return result

    def inventory(self) -> tuple[tuple[str, int], ...]:
        entries = []
        objects = self.root / "objects"
        if not objects.exists():
            return ()
        for path in sorted(objects.glob("*/*")):
            digest = path.parent.name + path.name
            fingerprint(digest)
            size = path.stat().st_size
            self.get(Entry(digest, size, "blob"))
            entries.append((digest, size))
        return tuple(entries)

    def collect(self, indexes: tuple[Index, ...], *, dry_run: bool = True) -> tuple[str, ...]:
        """Retain explicitly supplied live indexes; caller controls exclusive access."""
        live = {entry.digest for index in indexes for entry in index.entries}
        for index in indexes:
            for entry in index.entries:
                self.get(entry)
        unused = tuple(digest for digest, size in self.inventory() if digest not in live)
        if not dry_run:
            for digest in unused:
                self.path(digest).unlink()
        return unused

    def resolution_path(self, manifest_fingerprint: str) -> Path:
        digest = fingerprint(manifest_fingerprint)
        path = self.root / "resolutions" / (digest + ".json")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("resolution symlink escapes store root")
        return path

    def remember(self, manifest: Request, lockfile: Lockfile, proof: Proof) -> Path:
        """Cache a lockfile under its manifest fingerprint together with its proof."""

        if proof.manifest != manifest.fingerprint:
            raise ValueError("proof was produced for another manifest")
        path = self.resolution_path(manifest.fingerprint)
        payload = {
            "manifest": manifest.document(),
            "lock": lockfile.document(),
            "proof": proof.document(),
        }
        write(path, envelope(RESOLUTION_KIND, payload))
        return path

    def _cached(self, path: Path) -> tuple[Request, Lockfile, Proof]:
        payload = unwrap(read(path), RESOLUTION_KIND)
        if not isinstance(payload, dict) or set(payload) != {"manifest", "lock", "proof"}:
            raise ValueError("invalid cached resolution")
        return (
            load_request(payload["manifest"]),
            Lockfile.load(payload["lock"]),
            Proof.load(payload["proof"]),
        )

    def recall(self, manifest: Request, catalog: Repository) -> Lockfile | None:
        """Return the cached lockfile if its proof verifies under ``catalog``.

        A cached resolution whose proof no longer verifies is invalidated on
        the spot: the entry is removed and ``None`` is returned.
        """

        path = self.resolution_path(manifest.fingerprint)
        if not path.exists():
            return None
        _cached_manifest, lockfile, proof = self._cached(path)
        try:
            verify_proof(manifest, lockfile, proof, catalog)
        except ProofInvalid:
            path.unlink()
            return None
        return lockfile

    def cached(self) -> tuple[str, ...]:
        resolutions = self.root / "resolutions"
        if not resolutions.exists():
            return ()
        return tuple(sorted(fingerprint(path.stem) for path in resolutions.glob("*.json")))

    def invalidate(self, catalog: Repository) -> tuple[str, ...]:
        """Drop every cached resolution whose proof fails under ``catalog``."""

        removed = []
        for digest in self.cached():
            path = self.resolution_path(digest)
            manifest, lockfile, proof = self._cached(path)
            try:
                verify_proof(manifest, lockfile, proof, catalog)
            except ProofInvalid:
                path.unlink()
                removed.append(digest)
        return tuple(removed)
