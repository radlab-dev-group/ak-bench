"""Loading experiment descriptors from YAML (plan section 12).

Experiment definitions live in ``configs/experiments`` rather than in
``descriptors``, because they are the researcher's input rather than an
installed component: they name an agent, a dataset selection and a matrix, and
they reference the registries instead of being part of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from akbench.descriptors.registry import compute_digest
from akbench.experiments.descriptor import ExperimentDescriptor
from akbench.experiments.errors import ExperimentError

CONFIG_SUFFIXES = (".yaml", ".yml")


@dataclass(frozen=True)
class LoadedExperiment:
    """An experiment descriptor plus where it came from and its digest."""

    descriptor: ExperimentDescriptor
    path: Path | None = None
    digest: str = ""

    @property
    def identity(self) -> str:
        return self.descriptor.identity()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.descriptor.id,
            "version": self.descriptor.version,
            "title": self.descriptor.title,
            "identity": self.identity,
            "digest": self.digest,
            "path": str(self.path) if self.path else None,
        }


def parse_experiment(document: dict[str, Any], *, source: Path | None = None) -> LoadedExperiment:
    """Validate one parsed YAML document as an experiment descriptor."""
    if not isinstance(document, dict):
        raise ExperimentError(f"{_name(source)}: an experiment descriptor must be a mapping")
    try:
        descriptor = ExperimentDescriptor.model_validate(document)
    except ValidationError as exc:
        detail = f"{_name(source)}: invalid experiment descriptor:\n{_render(exc)}"
        raise ExperimentError(detail) from exc
    return LoadedExperiment(
        descriptor=descriptor,
        path=source,
        digest=compute_digest(document),
    )


def load_experiment_file(path: Path) -> LoadedExperiment:
    """Read and validate one experiment file."""
    target = Path(path)
    if not target.is_file():
        raise ExperimentError(f"experiment file not found: {target}")
    try:
        document = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ExperimentError(f"{target}: invalid YAML: {exc}") from exc
    return parse_experiment(document, source=target)


def load_experiment_directory(root: Path) -> list[LoadedExperiment]:
    """Load every experiment file under ``root``, sorted for a stable order."""
    directory = Path(root)
    if not directory.exists():
        return []
    files = sorted(
        path for path in directory.rglob("*") if path.is_file() and path.suffix in CONFIG_SUFFIXES
    )
    return [load_experiment_file(path) for path in files]


def _name(source: Path | None) -> str:
    return str(source) if source else "experiment"


def _render(exc: ValidationError) -> str:
    lines = []
    for issue in exc.errors():
        location = ".".join(str(part) for part in issue["loc"]) or "(root)"
        lines.append(f"  {location}: {issue['msg']}")
    return "\n".join(lines)
