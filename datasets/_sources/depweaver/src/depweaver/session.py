"""Revision-bound solver sessions with deterministic replay and atomic batches."""

from dataclasses import dataclass, replace

from .catalog import Revision
from .codec import envelope, unwrap
from .codec import request as load_request
from .errors import SearchLimit, Unsatisfiable
from .lockfile import Lockfile
from .model import Request, Resolution
from .proofs import Proof, prove
from .repository import Repository
from .resolver import Resolver
from .validation import require_valid


@dataclass(frozen=True)
class Record:
    name: str
    request: Request
    resolution: Resolution
    decisions: int
    conflicts: int

    def document(self) -> dict:
        return {
            "name": self.name,
            "request": self.request.document(),
            "lock": Lockfile(self.resolution).document(),
            "statistics": {"decisions": self.decisions, "conflicts": self.conflicts},
        }


@dataclass(frozen=True)
class Failure:
    name: str
    code: str
    explanation: dict

    def document(self) -> dict:
        return {"name": self.name, "code": self.code, "explanation": self.explanation}


@dataclass(frozen=True)
class Batch:
    completed: tuple[Record, ...]
    failed: tuple[Failure, ...]
    committed: bool

    @property
    def ok(self) -> bool:
        return not self.failed

    def document(self) -> dict:
        return {
            "committed": self.committed,
            "completed": [record.document() for record in self.completed],
            "failed": [failure.document() for failure in self.failed],
        }


class Session:
    def __init__(self, repository: Repository) -> None:
        self.repository = Repository(repository.all())
        self.solver = Resolver(self.repository)
        self.records: dict[str, Record] = {}
        self.order: list[str] = []

    def solve(self, name: str, request: Request, *, replace_existing: bool = False) -> Record:
        if not name or not isinstance(name, str):
            raise ValueError("session record name must be nonempty")
        if name in self.records and not replace_existing:
            raise ValueError("session record already exists")
        resolution = self.solver.solve(request)
        require_valid(self.repository, request, resolution)
        statistics = self.solver.statistics
        record = Record(name, request, resolution, statistics.decisions, statistics.conflicts)
        if name not in self.records:
            self.order.append(name)
        self.records[name] = record
        return record

    def batch(
        self, requests: dict[str, Request], *, atomic: bool = True, keep_going: bool = True
    ) -> Batch:
        collision = self.records.keys() & requests.keys()
        if collision or any(not isinstance(name, str) or not name for name in requests):
            raise ValueError("batch record names are invalid or already present")
        before, order = self.records.copy(), self.order.copy()
        completed, failed = [], []
        try:
            for name, request in sorted(requests.items()):
                try:
                    completed.append(self.solve(name, request))
                except Unsatisfiable as error:
                    failed.append(Failure(name, "unsatisfiable", error.conflict.document()))
                except SearchLimit as error:
                    failed.append(Failure(name, "search-limit", {"message": str(error)}))
                if failed and not keep_going:
                    break
        except Exception:
            self.records, self.order = before, order
            self.solver = Resolver(self.repository)
            raise
        committed = not (atomic and failed)
        if not committed:
            self.records, self.order = before, order
            self.solver = Resolver(self.repository)
        return Batch(tuple(completed), tuple(failed), committed)

    def drop(self, names: tuple[str, ...]) -> None:
        if set(names) - self.records.keys():
            raise KeyError("unknown session record")
        self.records = {name: record for name, record in self.records.items() if name not in names}
        self.order = [name for name in self.order if name not in names]

    def prove(self, name: str) -> Proof:
        """Proof of solution for a record, under this session's catalog snapshot."""
        record = self.records[name]
        return prove(self.repository, record.request, record.resolution)

    def update(self, name: str, packages: frozenset[str], *, as_name: str) -> Record:
        previous = self.records[name]
        request = Lockfile(previous.resolution).request(
            previous.request.roots, update=packages, policy=previous.request.policy
        )
        return self.solve(as_name, request)

    def revise(self, revision: Revision, *, preserve_records: bool = False) -> None:
        candidate = revision.apply(self.repository)
        records = {}
        if preserve_records:
            for name in self.order:
                previous = self.records[name]
                resolution = replace(
                    previous.resolution, repository_fingerprint=candidate.fingerprint
                )
                require_valid(candidate, previous.request, resolution)
                records[name] = replace(previous, resolution=resolution)
        self.repository = candidate
        self.records = records
        self.order = [name for name in self.order if name in records]
        self.solver = Resolver(candidate)

    def document(self) -> dict:
        return envelope(
            "session",
            {
                "repository": self.repository.document(),
                "records": [self.records[name].document() for name in self.order],
            },
        )

    @classmethod
    def load(cls, document: dict) -> "Session":
        payload = unwrap(document, "session")
        if not isinstance(payload, dict) or set(payload) != {"repository", "records"}:
            raise ValueError("invalid session payload")
        result = cls(Repository.load(payload["repository"]))
        for row in payload["records"]:
            name = row["name"]
            if not isinstance(name, str) or not name or name in result.records:
                raise ValueError("invalid or duplicate session record name")
            request = load_request(row["request"])
            resolution = Lockfile.load(row["lock"]).resolution
            require_valid(result.repository, request, resolution)
            statistics = row["statistics"]
            if set(statistics) != {"decisions", "conflicts"} or any(
                type(value) is not int or value < 0 for value in statistics.values()
            ):
                raise ValueError("invalid solver statistics")
            result.records[name] = Record(
                name, request, resolution, statistics["decisions"], statistics["conflicts"]
            )
            result.order.append(name)
        return result

    def replay(self) -> tuple[str, ...]:
        solver = Resolver(self.repository)
        different = []
        for name in self.order:
            record = self.records[name]
            actual = solver.solve(record.request)
            require_valid(self.repository, record.request, actual)
            if actual.document() != record.resolution.document():
                different.append(name)
        return tuple(different)
