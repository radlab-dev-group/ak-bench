"""Named project orchestration with portable state and transactional lock updates."""

from dataclasses import dataclass
from pathlib import Path

from .codec import envelope, read, unwrap, write
from .lockfile import Lockfile, diff
from .manifest import Manifest
from .matrix import Bundle
from .model import Request, normalize
from .repository import Repository
from .session import Batch, Session
from .validation import require_valid


@dataclass(frozen=True)
class Project:
    name: str
    manifest: Manifest
    profile: str | None = None
    groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", normalize(self.name))
        self.manifest.request(self.profile, groups=self.groups)

    def document(self) -> dict:
        return {
            "name": self.name,
            "manifest": self.manifest.document(),
            "profile": self.profile,
            "groups": list(self.groups),
        }

    def request(
        self, lock: Lockfile | None = None, update: frozenset[str] = frozenset()
    ) -> Request:
        request = self.manifest.request(self.profile, groups=self.groups)
        if lock is None:
            if update:
                raise ValueError("cannot update a project without a previous lock")
            return request
        return lock.request(
            request.roots, update=update, target=request.target, policy=request.policy
        )


class Workspace:
    def __init__(self, repository: Repository, projects: tuple[Project, ...] = ()) -> None:
        names = [project.name for project in projects]
        if len(names) != len(set(names)):
            raise ValueError("duplicate workspace project")
        self.repository = Repository(repository.all())
        self.projects = {project.name: project for project in projects}
        self.locks: dict[str, Lockfile] = {}
        self.requests: dict[str, Request] = {}
        self.revision = 0

    def configure(self, project: Project) -> None:
        previous = self.projects.get(project.name)
        self.projects[project.name] = project
        if previous != project:
            self.locks.pop(project.name, None)
            self.requests.pop(project.name, None)
            self.revision += 1

    def remove(self, name: str) -> None:
        name = normalize(name)
        del self.projects[name]
        self.locks.pop(name, None)
        self.requests.pop(name, None)
        self.revision += 1

    def solve(
        self,
        names: tuple[str, ...] = (),
        *,
        updates: dict[str, frozenset[str]] | None = None,
        atomic: bool = True,
    ) -> Batch:
        wanted = {normalize(name) for name in names} or set(self.projects)
        if wanted - self.projects.keys():
            raise ValueError("unknown workspace project")
        updates = {normalize(name): packages for name, packages in (updates or {}).items()}
        if updates.keys() - wanted:
            raise ValueError("update requested for an unselected project")
        requests = {
            name: self.projects[name].request(self.locks.get(name), updates.get(name, frozenset()))
            for name in sorted(wanted)
        }
        batch = Session(self.repository).batch(requests, atomic=atomic)
        if batch.committed:
            for record in batch.completed:
                self.locks[record.name] = Lockfile(record.resolution)
                self.requests[record.name] = record.request
            if batch.completed:
                self.revision += 1
        return batch

    def bundle(self, names: tuple[str, ...] = ()) -> Bundle:
        wanted = {normalize(name) for name in names} or set(self.projects)
        if wanted - self.locks.keys():
            raise ValueError("workspace has unlocked projects")
        return Bundle(tuple((name, self.locks[name].resolution) for name in sorted(wanted)))

    def status(self) -> dict:
        return {
            "revision": self.revision,
            "repository": self.repository.fingerprint,
            "projects": {
                name: {
                    "manifest": project.manifest.fingerprint,
                    "locked": name in self.locks,
                    "versions": self.locks[name].resolution.versions()
                    if name in self.locks
                    else {},
                }
                for name, project in sorted(self.projects.items())
            },
        }

    def compare(self, other: "Workspace") -> dict:
        shared = self.projects.keys() & other.projects.keys()
        return {
            "added": sorted(other.projects.keys() - self.projects.keys()),
            "removed": sorted(self.projects.keys() - other.projects.keys()),
            "configured": sorted(
                name for name in shared if self.projects[name] != other.projects[name]
            ),
            "locks": {
                name: diff(self.locks[name], other.locks[name])
                for name in sorted(self.locks.keys() & other.locks.keys())
                if self.locks[name] != other.locks[name]
            },
        }

    def document(self) -> dict:
        return envelope(
            "workspace",
            {
                "revision": self.revision,
                "repository": self.repository.document(),
                "projects": [project.document() for name, project in sorted(self.projects.items())],
                "locks": {name: lock.document() for name, lock in sorted(self.locks.items())},
                "requests": {
                    name: request.document() for name, request in sorted(self.requests.items())
                },
            },
        )

    @classmethod
    def load(cls, document: dict) -> "Workspace":
        from .codec import request

        payload = unwrap(document, "workspace")
        if not isinstance(payload, dict) or set(payload) != {
            "revision",
            "repository",
            "projects",
            "locks",
            "requests",
        }:
            raise ValueError("invalid workspace fields")
        if type(payload["revision"]) is not int or payload["revision"] < 0:
            raise ValueError("invalid workspace revision")
        projects = tuple(
            Project(
                row["name"], Manifest.load(row["manifest"]), row["profile"], tuple(row["groups"])
            )
            for row in payload["projects"]
        )
        result = cls(Repository.load(payload["repository"]), projects)
        result.revision = payload["revision"]
        if (
            payload["locks"].keys() != payload["requests"].keys()
            or payload["locks"].keys() - result.projects.keys()
        ):
            raise ValueError("workspace lock/request/project names disagree")
        for name, row in sorted(payload["locks"].items()):
            lock = Lockfile.load(row)
            original = request(payload["requests"][name])
            configured = result.projects[name].manifest.request(
                result.projects[name].profile, groups=result.projects[name].groups
            )
            if (
                configured.roots != original.roots
                or configured.target != original.target
                or configured.policy != original.policy
            ):
                raise ValueError("workspace request no longer matches project configuration")
            require_valid(result.repository, original, lock.resolution)
            result.locks[name], result.requests[name] = lock, original
        return result

    def save(self, path: Path) -> None:
        write(path, self.document())

    @classmethod
    def read(cls, path: Path) -> "Workspace":
        return cls.load(read(path))
