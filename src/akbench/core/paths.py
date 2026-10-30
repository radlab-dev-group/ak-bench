"""Project root discovery and resolved application paths.

Every writable location is derived from ``project_root`` so a run can be
relocated by pointing AK-Bench at another directory, which is what makes
per-run isolation and reproducibility manifests tractable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_MARKER = "pyproject.toml"
PROJECT_NAME = "ak-bench"
ENV_PROJECT_ROOT = "AKBENCH_HOME"


def resolve_project_root(start: Path | None = None, environ: dict[str, str] | None = None) -> Path:
    """Return the AK-Bench project root.

    Precedence: ``AKBENCH_HOME``, then the nearest ancestor of ``start`` whose
    ``pyproject.toml`` declares this project, then ``start`` itself.
    """
    env = os.environ if environ is None else environ
    override = env.get(ENV_PROJECT_ROOT)
    if override:
        return Path(override).expanduser().resolve()

    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        marker = candidate / PROJECT_MARKER
        if not marker.is_file():
            continue
        try:
            head = marker.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f'name = "{PROJECT_NAME}"' in head or f"name = '{PROJECT_NAME}'" in head:
            return candidate
    return origin


def resolve_path(value: str | Path, root: Path) -> Path:
    """Resolve a configured path against the project root, expanding ``~``."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (root / path).resolve()


@dataclass(frozen=True)
class AppPaths:
    """Absolute, resolved locations AK-Bench reads and writes."""

    project_root: Path
    data_dir: Path
    artifacts_dir: Path
    workspaces_dir: Path
    runtime_instances_dir: Path
    reports_dir: Path
    descriptors_dir: Path
    database_file: Path
    logs_dir: Path | None = None
    created: list[Path] = field(default_factory=list, compare=False, repr=False)

    def writable_dirs(self) -> list[Path]:
        return [
            self.data_dir,
            self.artifacts_dir,
            self.workspaces_dir,
            self.runtime_instances_dir,
            self.reports_dir,
            self.descriptors_dir,
            *([self.logs_dir] if self.logs_dir else []),
        ]

    def ensure(self) -> list[Path]:
        """Create missing directories. Returns the paths that were created."""
        created: list[Path] = []
        for directory in self.writable_dirs():
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created.append(directory)
            elif not directory.is_dir():
                raise NotADirectoryError(f"not a directory: {directory}")
        return created

    def report(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in (
                ("project_root", self.project_root),
                ("data_dir", self.data_dir),
                ("artifacts_dir", self.artifacts_dir),
                ("workspaces_dir", self.workspaces_dir),
                ("runtime_instances_dir", self.runtime_instances_dir),
                ("reports_dir", self.reports_dir),
                ("descriptors_dir", self.descriptors_dir),
                ("database_file", self.database_file),
                ("logs_dir", self.logs_dir),
            )
            if value is not None
        }
