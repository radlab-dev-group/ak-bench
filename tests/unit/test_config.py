from __future__ import annotations

from pathlib import Path

import pytest

from akbench.config.loader import (
    build_app_paths,
    deep_merge,
    env_overrides,
    load_settings,
    resolve_database_url,
)
from akbench.config.models import Settings
from akbench.core.errors import ConfigError


def test_defaults_load_without_file(project_dir: Path, empty_environ: dict[str, str]) -> None:
    loaded = load_settings(None, project_root=project_dir, environ=empty_environ)
    assert loaded.source.value == "builtin_defaults"
    assert loaded.settings.paths.data_dir == Path("data")
    assert loaded.settings.schema_version == 1


def test_file_config_overrides_defaults(project_dir: Path, empty_environ: dict[str, str]) -> None:
    config = project_dir / "configs" / "defaults.yaml"
    config.parent.mkdir()
    config.write_text("logging:\n  level: DEBUG\n", encoding="utf-8")
    empty_environ["AKBENCH_CONFIG"] = str(config)

    loaded = load_settings(None, project_root=project_dir, environ=empty_environ)
    assert loaded.source.value == "env"
    assert loaded.settings.logging.level == "DEBUG"
    # untouched sections keep their defaults
    assert loaded.settings.doctor.required_tools == ["git"]


def test_env_override_beats_file(project_dir: Path, empty_environ: dict[str, str]) -> None:
    config = project_dir / "config.yaml"
    config.write_text("logging:\n  level: DEBUG\n", encoding="utf-8")
    empty_environ["AKBENCH_CONFIG"] = str(config)
    empty_environ["AKBENCH__LOGGING__LEVEL"] = "ERROR"

    loaded = load_settings(None, project_root=project_dir, environ=empty_environ)
    assert loaded.settings.logging.level == "ERROR"


def test_env_override_parses_yaml_scalars(empty_environ: dict[str, str]) -> None:
    empty_environ["AKBENCH__DATABASE__TIMEOUT_SECONDS"] = "5"
    empty_environ["AKBENCH__DOCTOR__REQUIRED_TOOLS"] = "[git, hg]"
    overrides = env_overrides(empty_environ)
    assert overrides["database"]["timeout_seconds"] == 5
    assert overrides["doctor"]["required_tools"] == ["git", "hg"]


def test_unknown_key_is_rejected(project_dir: Path, empty_environ: dict[str, str]) -> None:
    config = project_dir / "bad.yaml"
    config.write_text("nope:\n  level: DEBUG\n", encoding="utf-8")
    empty_environ["AKBENCH_CONFIG"] = str(config)

    with pytest.raises(ConfigError, match="nope"):
        load_settings(None, project_root=project_dir, environ=empty_environ)


def test_invalid_level_is_rejected(project_dir: Path, empty_environ: dict[str, str]) -> None:
    config = project_dir / "bad.yaml"
    config.write_text("logging:\n  level: CHATTY\n", encoding="utf-8")
    empty_environ["AKBENCH_CONFIG"] = str(config)

    with pytest.raises(ConfigError, match=r"logging\.level"):
        load_settings(None, project_root=project_dir, environ=empty_environ)


def test_explicit_missing_config_file_fails(
    project_dir: Path, empty_environ: dict[str, str]
) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_settings(project_dir / "missing.yaml", environ=empty_environ)


def test_database_url_defaults_to_file(project_dir: Path, empty_environ: dict[str, str]) -> None:
    loaded = load_settings(None, project_root=project_dir, environ=empty_environ)
    url = resolve_database_url(loaded.settings, environ=empty_environ)
    assert url == f"sqlite:///{project_dir / 'data' / 'akbench.sqlite'}"


def test_database_url_explicit_wins(project_dir: Path, empty_environ: dict[str, str]) -> None:
    loaded = load_settings(None, project_root=project_dir, environ=empty_environ)
    explicit = "postgresql://user@host/db"
    settings = Settings.model_validate(
        {
            **loaded.settings.model_dump(),
            "project_root": str(project_dir),
            "database": {"url": explicit},
        }
    )
    assert resolve_database_url(settings) == explicit


def test_build_app_paths_resolves_relative(
    project_dir: Path, empty_environ: dict[str, str]
) -> None:
    loaded = load_settings(None, project_root=project_dir, environ=empty_environ)
    paths = build_app_paths(loaded.settings, environ=empty_environ)
    assert paths.project_root == project_dir.resolve()
    assert paths.database_file == (project_dir / "data" / "akbench.sqlite").resolve()
    assert paths.logs_dir is not None


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"b": 10}, "e": 5}
    merged = deep_merge(base, override)
    assert merged == {"a": {"b": 10, "c": 2}, "d": 3, "e": 5}
    assert base == {"a": {"b": 1, "c": 2}, "d": 3}
