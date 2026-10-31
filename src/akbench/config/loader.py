"""Configuration discovery, merging and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from akbench.config.models import Settings
from akbench.core.errors import ConfigError
from akbench.core.paths import AppPaths, resolve_path, resolve_project_root

DEFAULT_CONFIG_RELPATH = Path("configs/defaults.yaml")
ENV_CONFIG_PATH = "AKBENCH_CONFIG"
ENV_OVERRIDE_PREFIX = "AKBENCH__"
ENV_NESTED_SEPARATOR = "__"


class ConfigSource(StrEnum):
    CLI = "cli"
    ENV = "env"
    PROJECT_FILE = "project_file"
    BUILTIN_DEFAULTS = "builtin_defaults"


@dataclass(frozen=True)
class LoadedConfig:
    """Settings plus where they came from, so runs can record provenance."""

    settings: Settings
    path: Path | None
    source: ConfigSource

    def describe(self) -> str:
        if self.path is None:
            return str(self.source)
        return f"{self.source}: {self.path}"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base`` without mutating either."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_env_value(raw: str) -> Any:
    """Interpret an environment value as YAML, falling back to the raw string."""
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def env_overrides(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Collect ``AKBENCH__SECTION__FIELD`` overrides into a nested dict."""
    env = os.environ if environ is None else environ
    collected: dict[str, Any] = {}
    for name, raw in env.items():
        if not name.startswith(ENV_OVERRIDE_PREFIX):
            continue
        dotted = name[len(ENV_OVERRIDE_PREFIX) :].lower()
        if not dotted:
            continue
        node = collected
        parts = dotted.split(ENV_NESTED_SEPARATOR)
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):  # pragma: no cover - defensive
                raise ConfigError(f"conflicting environment override: {name}")
        node[parts[-1]] = _parse_env_value(raw)
    return collected


def discover_config_file(
    explicit: Path | None = None,
    root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[Path | None, ConfigSource]:
    env = os.environ if environ is None else environ

    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path, ConfigSource.CLI

    from_env = env.get(ENV_CONFIG_PATH)
    if from_env:
        path = Path(from_env).expanduser().resolve()
        if not path.is_file():
            raise ConfigError(f"{ENV_CONFIG_PATH} points to a missing file: {path}")
        return path, ConfigSource.ENV

    base = root or resolve_project_root(environ=env)
    candidate = base / DEFAULT_CONFIG_RELPATH
    if candidate.is_file():
        return candidate, ConfigSource.PROJECT_FILE
    return None, ConfigSource.BUILTIN_DEFAULTS


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping: {path}")
    return data


def load_settings(
    config_path: Path | str | None = None,
    *,
    project_root: Path | str | None = None,
    environ: dict[str, str] | None = None,
) -> LoadedConfig:
    """Build validated settings from built-ins, an optional file and env overrides."""
    env = os.environ if environ is None else environ
    root = (
        Path(project_root).expanduser().resolve()
        if project_root
        else resolve_project_root(environ=env)
    )

    explicit = Path(config_path).expanduser() if config_path else None
    path, source = discover_config_file(explicit, root, env)

    data: dict[str, Any] = {}
    if path is not None:
        data = _read_yaml(path)
    data = deep_merge(data, env_overrides(env))
    data.setdefault("project_root", str(root))

    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {_render_validation_error(exc)}") from exc
    return LoadedConfig(settings=settings, path=path, source=source)


def _render_validation_error(exc: ValidationError) -> str:
    lines = []
    for issue in exc.errors():
        location = ".".join(str(part) for part in issue["loc"]) or "<root>"
        lines.append(f"{location}: {issue['msg']}")
    return "; ".join(lines)


def build_app_paths(settings: Settings, environ: dict[str, str] | None = None) -> AppPaths:
    """Resolve configured (possibly relative) paths against the project root."""
    root = (
        settings.project_root.resolve()
        if settings.project_root
        else resolve_project_root(environ=environ)
    )
    paths = settings.paths
    return AppPaths(
        project_root=root,
        data_dir=resolve_path(paths.data_dir, root),
        artifacts_dir=resolve_path(paths.artifacts_dir, root),
        workspaces_dir=resolve_path(paths.workspaces_dir, root),
        runtime_instances_dir=resolve_path(paths.runtime_instances_dir, root),
        reports_dir=resolve_path(paths.reports_dir, root),
        descriptors_dir=resolve_path(paths.descriptors_dir, root),
        datasets_dir=resolve_path(paths.datasets_dir, root),
        repositories_dir=resolve_path(paths.repositories_dir, root),
        database_file=resolve_path(paths.database_file, root),
        logs_dir=resolve_path(paths.logs_dir, root) if paths.logs_dir else None,
    )


def resolve_database_url(settings: Settings, environ: dict[str, str] | None = None) -> str:
    """Return the effective SQLAlchemy URL (explicit URL wins over the file path)."""
    if settings.database.url:
        return settings.database.url
    return f"sqlite:///{build_app_paths(settings, environ).database_file}"
