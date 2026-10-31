"""Dataset discovery and validation (plan sections 8.1 to 8.6).

Layout: ``<datasets>/<category>/<task-id>/task.yaml``. The category comes from
the descriptor registry, not from a hardcoded enum, so registering a category is
a descriptor change (plan 8.1).

A task's snapshot digest covers the descriptor *and* the bytes that define the
task (mutation patch, hidden tests, public tests, description): editing a hidden
test changes the digest, so a historical result cannot be reinterpreted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from akbench.core.errors import DescriptorError
from akbench.datasets.task import TaskDescriptor
from akbench.descriptors import DescriptorKind, DescriptorRegistry

TASK_FILE = "task.yaml"
DESCRIPTION_FILE = "description.md"


class TaskLoadError(Exception):
    """A task file cannot be read or does not validate."""


@dataclass(frozen=True)
class LoadedTask:
    """A task plus where it came from and the digest of everything it depends on."""

    task: TaskDescriptor
    path: Path
    digest: str

    @property
    def uid(self) -> str:
        return self.task.uid

    def as_dict(self) -> dict[str, object]:
        return {
            "uid": self.uid,
            "id": self.task.id,
            "version": self.task.version,
            "category": self.task.category,
            "difficulty": self.task.difficulty,
            "evaluator": self.task.evaluator,
            "digest": self.digest,
            "path": str(self.path),
        }


@dataclass
class TaskValidation:
    """Per-task validation outcome."""

    task_uid: str | None
    path: str
    issues: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def fail(self, check: str, message: str) -> None:
        self.checks[check] = "fail"
        self.issues.append(message)

    def pass_check(self, check: str, detail: str = "ok") -> None:
        self.checks.setdefault(check, "ok")
        if detail != "ok":
            self.checks[check] = detail

    def as_dict(self) -> dict[str, object]:
        return {
            "task": self.task_uid,
            "path": self.path,
            "ok": self.ok,
            "issues": self.issues,
            "checks": self.checks,
        }


@dataclass(frozen=True)
class DatasetReport:
    tasks: list[TaskValidation]

    @property
    def failed(self) -> list[TaskValidation]:
        return [task for task in self.tasks if not task.ok]

    @property
    def ok(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict[str, object]:
        return {
            "tasks": len(self.tasks),
            "ok": self.ok,
            "failed": len(self.failed),
            "results": [task.as_dict() for task in self.tasks],
        }


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(directory: Path) -> str:
    """Digest over a directory tree, independent of file order and mtimes."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def compute_task_digest(task_dir: Path, task: TaskDescriptor) -> str:
    """Canonical digest of a task: descriptor plus the files that define it."""
    payload: dict[str, Any] = {
        "descriptor": json.loads(task.model_dump_json()),
        "files": {},
    }
    body = task.task
    candidates: list[tuple[str, Path]] = [(DESCRIPTION_FILE, task_dir / DESCRIPTION_FILE)]
    if body.mutation is not None:
        candidates.append(("mutation", task_dir / body.mutation.patch))
    if body.hidden_tests:
        candidates.append(("hidden_tests", task_dir / body.hidden_tests))
    if body.public_tests:
        candidates.append(("public_tests", task_dir / body.public_tests))

    for name, candidate in candidates:
        if not candidate.exists():
            continue
        if candidate.is_dir():
            payload["files"][name] = f"tree:{_tree_digest(candidate)}"
        else:
            payload["files"][name] = f"sha256:{_file_digest(candidate)}"

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def task_directories(root: Path) -> list[Path]:
    """Task directories under ``<root>/<category>/<task>`` that hold a task.yaml."""
    root = Path(root)
    if not root.exists():
        return []
    found: list[Path] = []
    for category_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for task_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            if (task_dir / TASK_FILE).is_file():
                found.append(task_dir)
    return found


def load_task(task_dir: Path) -> LoadedTask:
    """Read and validate one task directory."""
    directory = Path(task_dir)
    path = directory / TASK_FILE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TaskLoadError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise TaskLoadError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise TaskLoadError(f"{path}: task root must be a mapping")

    try:
        task = TaskDescriptor.model_validate(raw)
    except ValidationError as exc:
        issues = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or '<root>'}: {issue['msg']}"
            for issue in exc.errors()
        )
        raise TaskLoadError(f"invalid task in {path}: {issues}") from exc

    return LoadedTask(task=task, path=directory, digest=compute_task_digest(directory, task))


class Dataset:
    """Loaded tasks, addressable by id/version, plus validation against registries."""

    def __init__(self, root: Path, tasks: list[LoadedTask], base_dir: Path | None = None) -> None:
        self.root = Path(root)
        # relative repository sources are resolved against this, which is the
        # project root for the conventional ``<project>/datasets`` layout
        self.base_dir = Path(base_dir) if base_dir else self.root.parent
        self._tasks = tasks

    @classmethod
    def load(cls, root: Path, base_dir: Path | None = None) -> Dataset:
        root = Path(root)
        if not root.exists():
            raise TaskLoadError(f"dataset directory not found: {root}")
        tasks = [load_task(task_dir) for task_dir in task_directories(root)]
        dataset = cls(root, tasks, base_dir=base_dir)
        dataset._check_unique_uids()
        return dataset

    def resolve_source(self, source: str) -> str:
        """Absolute path for a relative local source; URLs are returned unchanged."""
        if "://" in source or source.startswith("git@"):
            return source
        candidate = Path(source).expanduser()
        if candidate.is_absolute():
            return str(candidate)
        return str((self.base_dir / candidate).resolve())

    def materialize(self, loaded: LoadedTask) -> LoadedTask:
        """Same task with its repository source resolved to an absolute path."""
        resolved = self.resolve_source(loaded.task.task.repository.source)
        if resolved == loaded.task.task.repository.source:
            return loaded
        repository = loaded.task.task.repository.model_copy(update={"source": resolved})
        body = loaded.task.task.model_copy(update={"repository": repository})
        task = loaded.task.model_copy(update={"task": body})
        return LoadedTask(task=task, path=loaded.path, digest=loaded.digest)

    def _check_unique_uids(self) -> None:
        seen: dict[str, str] = {}
        for loaded in self._tasks:
            previous = seen.get(loaded.uid)
            if previous is not None and previous != str(loaded.path):
                raise TaskLoadError(
                    f"duplicate task uid {loaded.uid}: {previous} and {loaded.path}"
                )
            seen[loaded.uid] = str(loaded.path)

    def __len__(self) -> int:
        return len(self._tasks)

    def __iter__(self):
        return iter(self._tasks)

    @property
    def tasks(self) -> list[LoadedTask]:
        return list(self._tasks)

    def ids(self, category: str | None = None) -> list[str]:
        wanted = None if category is None else category
        matching = [
            loaded.task.id
            for loaded in self._tasks
            if wanted is None or loaded.task.category == wanted
        ]
        return sorted(set(matching))

    def get(self, task_id: str, version: str | None = None) -> LoadedTask | None:
        wanted_id, wanted_version = task_id, version
        if version is None and "@" in task_id:
            wanted_id, wanted_version = task_id.split("@", 1)
        matches = [loaded for loaded in self._tasks if loaded.task.id == wanted_id]
        if wanted_version is not None:
            matches = [loaded for loaded in matches if loaded.task.version == wanted_version]
        if not matches:
            return None
        return sorted(matches, key=lambda loaded: loaded.task.version)[-1]

    def require(self, task_id: str, version: str | None = None) -> LoadedTask:
        found = self.get(task_id, version)
        if found is None:
            known = ", ".join(self.ids()) or "none"
            wanted = task_id if version is None else f"{task_id}@{version}"
            raise TaskLoadError(f"unknown task {wanted!r}; registered tasks: {known}")
        return found

    def categories(self) -> list[str]:
        return sorted({loaded.task.category for loaded in self._tasks})

    def validate(
        self,
        registry: DescriptorRegistry | None = None,
        *,
        check_repositories: bool = False,
    ) -> DatasetReport:
        """Cross-check every task against the descriptor registries.

        ``check_repositories`` additionally asks git whether each pinned ref
        resolves; it is opt-in because it touches the network for remote
        sources.
        """
        results = [
            self._validate_one(loaded, registry, check_repositories) for loaded in self._tasks
        ]
        return DatasetReport(tasks=results)

    def _validate_one(
        self,
        loaded: LoadedTask,
        registry: DescriptorRegistry | None,
        check_repositories: bool,
    ) -> TaskValidation:
        task = loaded.task
        body = task.task
        result = TaskValidation(task_uid=loaded.uid, path=str(loaded.path))

        if loaded.path.name != task.id:
            result.fail(
                "directory", f"task id {task.id!r} does not match directory {loaded.path.name!r}"
            )
        else:
            result.pass_check("directory")

        if loaded.path.parent.name != body.category:
            result.fail(
                "category_dir",
                f"category {body.category!r} does not match directory {loaded.path.parent.name!r}",
            )
        else:
            result.pass_check("category_dir")

        if not (loaded.path / DESCRIPTION_FILE).is_file() and not task.description:
            result.fail(
                "description",
                f"neither {DESCRIPTION_FILE} nor a description field is present; "
                "an agent needs a task statement",
            )
        else:
            result.pass_check("description")

        hidden = loaded.path / body.hidden_tests
        if not hidden.is_dir():
            result.fail("hidden_tests", f"hidden tests directory not found: {hidden}")
        elif not any(hidden.rglob("*")):
            result.fail("hidden_tests", f"hidden tests directory is empty: {hidden}")
        else:
            result.pass_check("hidden_tests")

        if body.public_tests:
            public = loaded.path / body.public_tests
            if not public.is_dir():
                result.fail("public_tests", f"public tests directory not found: {public}")
            else:
                result.pass_check("public_tests")

        if body.mutation is not None:
            patch = loaded.path / body.mutation.patch
            if not patch.is_file():
                result.fail("mutation", f"mutation patch not found: {patch}")
            elif not patch.read_text(encoding="utf-8", errors="replace").strip():
                result.fail("mutation", f"mutation patch is empty: {patch}")
            else:
                result.pass_check("mutation")

        if registry is not None:
            self._validate_against_registry(loaded, registry, result)

        if check_repositories:
            from akbench.datasets.repository import RepositoryManager

            manager = RepositoryManager(self.base_dir / "data" / "repositories")
            check = manager.check(
                self.resolve_source(body.repository.source), body.repository.ref
            )
            if not check.ok:
                result.fail("repository", check.detail)
            else:
                result.checks["repository"] = f"commit {check.commit[:12]}"

        return result

    def _validate_against_registry(
        self,
        loaded: LoadedTask,
        registry: DescriptorRegistry,
        result: TaskValidation,
    ) -> None:
        task = loaded.task
        body = task.task

        try:
            category = registry.get(DescriptorKind.CATEGORY, body.category)
        except DescriptorError as exc:  # pragma: no cover - get() does not raise
            result.fail("category", str(exc))
            category = None

        if category is None:
            result.fail(
                "category",
                f"category {body.category!r} is not registered; add a Category Descriptor",
            )
        elif not category.descriptor.category.enabled:
            result.fail("category", f"category {body.category!r} is registered but disabled")
        else:
            difficulties = category.descriptor.category.difficulties
            if task.difficulty not in difficulties:
                result.fail(
                    "difficulty",
                    f"difficulty {task.difficulty!r} is not allowed by category "
                    f"{body.category!r} (allowed: {', '.join(difficulties)})",
                )
            else:
                result.pass_check("category")
                result.pass_check("difficulty")

        evaluator = registry.get(DescriptorKind.EVALUATOR, body.evaluator)
        if evaluator is None:
            result.fail(
                "evaluator",
                f"evaluator {body.evaluator!r} is not registered; add an Evaluator Descriptor",
            )
        else:
            result.pass_check("evaluator")


def load_dataset(
    root: Path,
    registry: DescriptorRegistry | None = None,
) -> Dataset:
    """Load a dataset directory; ``registry`` is kept for symmetry with validate."""
    return Dataset.load(root)
