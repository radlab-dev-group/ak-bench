"""Environment diagnostics behind ``akbench doctor``.

Checks are expressed against configuration only: required and optional tools
come from ``doctor.required_tools`` / ``doctor.optional_tools``, so nothing
here knows which agent is going to be benchmarked (plan rule 3).
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from akbench import MIN_PYTHON_VERSION, __version__
from akbench.config.loader import LoadedConfig, build_app_paths, resolve_database_url
from akbench.core.errors import DatabaseError
from akbench.storage.db import create_db_engine, engine_is_reachable
from akbench.storage.migrator import schema_status


class CheckStatus(StrEnum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    FAIL = "fail"

    @property
    def blocks(self) -> bool:
        return self is CheckStatus.FAIL


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    hint: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"name": self.name, "status": str(self.status), "detail": self.detail}
        if self.hint:
            payload["hint"] = self.hint
        return payload


@dataclass(frozen=True)
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is CheckStatus.FAIL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is CheckStatus.WARNING]

    @property
    def ok(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict[str, object]:
        return {
            "akbench_version": __version__,
            "ok": self.ok,
            "summary": {
                "checks": len(self.checks),
                "failed": len(self.failed),
                "warnings": len(self.warnings),
            },
            "checks": [check.as_dict() for check in self.checks],
        }


def check_python() -> CheckResult:
    required = ".".join(str(part) for part in MIN_PYTHON_VERSION)
    current = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < MIN_PYTHON_VERSION:
        return CheckResult(
            "python_runtime",
            CheckStatus.FAIL,
            f"Python {current} < required {required}",
            hint="create the virtualenv with Python 3.12+, e.g. `uv venv --python 3.12`",
        )
    return CheckResult("python_runtime", CheckStatus.OK, f"Python {current}")


def resolve_package(name: str) -> tuple[str, str]:
    """Return ``(version, origin)`` for a distribution name or an import name.

    Distribution metadata is authoritative, but some names in configuration are
    import names whose distribution differs (``yaml`` ships as ``PyYAML``), so an
    importable module with a ``__version__`` also counts.
    """
    try:
        return importlib.metadata.version(name), "distribution"
    except importlib.metadata.PackageNotFoundError:
        pass

    try:
        module = importlib.import_module(name)
    except Exception:
        raise importlib.metadata.PackageNotFoundError(name) from None

    version = getattr(module, "__version__", None)
    if not version:
        raise importlib.metadata.PackageNotFoundError(name)
    return str(version), "module"


def check_packages(names: list[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in names:
        try:
            version, origin = resolve_package(name)
        except importlib.metadata.PackageNotFoundError:
            results.append(
                CheckResult(
                    f"package:{name}",
                    CheckStatus.FAIL,
                    f"{name} is not installed",
                    hint=f"`uv pip install {name}`",
                )
            )
        else:
            detail = version if origin == "distribution" else f"{version} (import {name})"
            results.append(CheckResult(f"package:{name}", CheckStatus.OK, detail))
    return results


def check_config(loaded: LoadedConfig) -> CheckResult:
    if loaded.source.value == "builtin_defaults":
        return CheckResult(
            "config",
            CheckStatus.INFO,
            "no config file found, using built-in defaults",
            hint="`akbench init` writes configs/defaults.yaml",
        )
    return CheckResult("config", CheckStatus.OK, loaded.describe())


def check_directories(paths: list[Path]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for directory in paths:
        if not directory.exists():
            results.append(
                CheckResult(
                    f"dir:{directory.name}",
                    CheckStatus.FAIL,
                    f"{directory} does not exist",
                    hint="`akbench init`",
                )
            )
        elif not directory.is_dir():
            results.append(
                CheckResult(f"dir:{directory.name}", CheckStatus.FAIL, f"{directory} is not a directory")
            )
        elif not os.access(directory, os.W_OK):
            results.append(
                CheckResult(f"dir:{directory.name}", CheckStatus.FAIL, f"{directory} is not writable")
            )
        else:
            results.append(CheckResult(f"dir:{directory.name}", CheckStatus.OK, str(directory)))
    return results


def check_database(database_url: str) -> list[CheckResult]:
    engine = None
    try:
        engine = create_db_engine(database_url)
        engine_is_reachable(engine)
    except DatabaseError as exc:
        return [
            CheckResult("database", CheckStatus.FAIL, str(exc), hint="`akbench init` creates the SQLite file")
        ]
    finally:
        if engine is not None:
            engine.dispose()

    status = schema_status(database_url)
    if not status.initialized:
        return [
            CheckResult(
                "database",
                CheckStatus.OK,
                f"reachable, schema not created ({status.describe()})",
                hint="`akbench init` applies migrations",
            ),
            CheckResult("schema", CheckStatus.FAIL, "tables missing", hint="`akbench init`"),
        ]
    if not status.at_head:
        return [
            CheckResult("database", CheckStatus.OK, "reachable"),
            CheckResult(
                "schema",
                CheckStatus.FAIL,
                status.describe(),
                hint="`akbench init` applies pending migrations",
            ),
        ]
    return [
        CheckResult("database", CheckStatus.OK, "reachable"),
        CheckResult("schema", CheckStatus.OK, status.describe()),
    ]


def check_tools(tools: list[str], *, required: bool) -> list[CheckResult]:
    results: list[CheckResult] = []
    for tool in tools:
        found = shutil.which(tool)
        if found:
            results.append(CheckResult(f"tool:{tool}", CheckStatus.OK, found))
        elif required:
            results.append(
                CheckResult(f"tool:{tool}", CheckStatus.FAIL, f"{tool} not found in PATH", hint=f"install {tool}")
            )
        else:
            results.append(
                CheckResult(
                    f"tool:{tool}",
                    CheckStatus.INFO,
                    f"{tool} not found (optional)",
                    hint="needed only for containerised sandboxing",
                )
            )
    return results


def check_disk(path: Path, min_free_mb: int) -> CheckResult:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        return CheckResult("disk", CheckStatus.WARNING, f"cannot read disk usage for {probe}: {exc}")
    free_mb = usage.free // (1024 * 1024)
    if free_mb < min_free_mb:
        return CheckResult(
            "disk",
            CheckStatus.WARNING,
            f"{free_mb} MB free at {probe}, configured minimum {min_free_mb} MB",
            hint="runs and artifacts need space; point paths.* elsewhere in the config",
        )
    return CheckResult("disk", CheckStatus.OK, f"{free_mb} MB free at {probe}")


def run_diagnostics(loaded: LoadedConfig, environ: dict[str, str] | None = None) -> DoctorReport:
    settings = loaded.settings
    paths = build_app_paths(settings, environ)
    doctor = settings.doctor

    checks: list[CheckResult] = [check_python()]
    checks.extend(check_packages(doctor.required_packages))
    checks.append(check_config(loaded))
    checks.extend(check_directories(paths.writable_dirs()))
    checks.extend(check_database(resolve_database_url(settings, environ)))
    checks.extend(check_tools(doctor.required_tools, required=True))
    checks.extend(check_tools(doctor.optional_tools, required=False))
    checks.append(check_disk(paths.data_dir, doctor.min_free_disk_mb))
    return DoctorReport(checks=checks)
