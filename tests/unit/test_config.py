from __future__ import annotations

from pathlib import Path

import pytest

from akbench.config.loader import (
    build_app_paths,
    connection_overrides,
    deep_merge,
    env_overrides,
    load_settings,
    redact_database_url,
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


def test_sqlite_is_the_default_backend(project_dir: Path, empty_environ: dict[str, str]) -> None:
    """A fresh clone records to a file, with no server and no credential.

    SQLite is the built-in backend so that ``akbench init`` and ``doctor`` work
    on a checkout that has never seen a database; the shared mode is chosen
    explicitly, and choosing it is what makes its credential required.
    """
    environ = {key: value for key, value in empty_environ.items() if key != "AKBENCH_DB_BACKEND"}
    loaded = load_settings(None, project_root=project_dir, environ=environ)
    assert loaded.settings.database.backend == "sqlite"
    url = resolve_database_url(loaded.settings, environ=environ)
    assert url == f"sqlite:///{project_dir / 'data' / 'akbench.sqlite'}"


def test_postgres_is_the_opt_in_shared_backend(
    project_dir: Path, empty_environ: dict[str, str]
) -> None:
    """Asking for the shared engine asks for its login with it.

    There is no password to fall back on, so resolving a connection out of the
    built-in defaults is refused rather than made up: the alternative is an
    installation that quietly shares a credential with everyone who has read the
    repository.
    """
    environ = {
        **{key: value for key, value in empty_environ.items() if key != "AKBENCH_DB_BACKEND"},
        "AKBENCH_DB_BACKEND": "postgres",
    }
    loaded = load_settings(None, project_root=project_dir, environ=environ)
    assert loaded.settings.database.backend == "postgres"
    assert loaded.settings.database.postgres.password is None

    with pytest.raises(ConfigError, match="AKBENCH_PG_PASSWORD"):
        resolve_database_url(loaded.settings, environ=environ)

    environ["AKBENCH_PG_PASSWORD"] = "a password with length and no idea behind it"
    loaded = load_settings(None, project_root=project_dir, environ=environ)
    assert resolve_database_url(loaded.settings, environ=environ).startswith(
        "postgresql+psycopg://"
    )


def test_sqlite_backend_selects_the_configured_file(
    project_dir: Path, empty_environ: dict[str, str]
) -> None:
    loaded = load_settings(None, project_root=project_dir, environ=empty_environ)
    assert loaded.settings.database.backend == "sqlite"
    url = resolve_database_url(loaded.settings, environ=empty_environ)
    assert url == f"sqlite:///{project_dir / 'data' / 'akbench.sqlite'}"


def test_postgres_connection_comes_from_the_env_file(
    project_dir: Path, empty_environ: dict[str, str]
) -> None:
    """One .env configures the helper script and the engine."""
    (project_dir / ".env").write_text(
        "AKBENCH_DB_BACKEND=postgres\n"
        "AKBENCH_PG_HOST=db.internal\n"
        "AKBENCH_PG_PORT=6543\n"
        "AKBENCH_PG_USER=akbench\n"
        'AKBENCH_PG_PASSWORD="secret words"\n'
        "AKBENCH_PG_DB=akbench_prod\n",
        encoding="utf-8",
    )
    environ = {key: value for key, value in empty_environ.items() if key != "AKBENCH_DB_BACKEND"}
    loaded = load_settings(None, project_root=project_dir, environ=environ)
    assert loaded.dotenv_path == project_dir / ".env"
    assert loaded.settings.database.backend == "postgres"
    assert loaded.settings.database.postgres.port == 6543
    assert loaded.settings.database.postgres.password.get_secret_value() == "secret words"
    # The password is a secret even inside the settings object: `config show
    # --json` dumps the whole thing, and what that output gets pasted into is
    # not something this project controls.
    assert "secret words" not in str(loaded.settings.model_dump(mode="json"))
    url = resolve_database_url(loaded.settings, environ=environ)
    assert url == "postgresql+psycopg://akbench:secret%20words@db.internal:6543/akbench_prod"


def test_exported_environment_beats_the_env_file(
    project_dir: Path, empty_environ: dict[str, str]
) -> None:
    (project_dir / ".env").write_text("AKBENCH_PG_DB=from_file\n", encoding="utf-8")
    environ = {**empty_environ, "AKBENCH_PG_DB": "from_shell"}
    loaded = load_settings(None, project_root=project_dir, environ=environ)
    assert loaded.settings.database.postgres.database == "from_shell"


def test_akbench_override_beats_the_connection_variables(
    project_dir: Path, empty_environ: dict[str, str]
) -> None:
    """AKBENCH__DATABASE__* is the explicit word; AKBENCH_PG_* only states a connection."""
    environ = {
        **empty_environ,
        "AKBENCH_PG_DB": "from_env",
        "AKBENCH__DATABASE__BACKEND": "sqlite",
    }
    loaded = load_settings(None, project_root=project_dir, environ=environ)
    assert loaded.settings.database.backend == "sqlite"
    assert loaded.settings.database.postgres.database == "from_env"


def test_connection_overrides_map_named_variables() -> None:
    overrides = connection_overrides(
        {"AKBENCH_PG_HOST": "h", "AKBENCH_PG_PORT": "5432", "AKBENCH_PG_PASSWORD": "***"}
    )
    assert overrides == {"database": {"postgres": {"host": "h", "port": 5432, "password": "***"}}}
    assert connection_overrides({"PATH": "/usr/bin"}) == {}


def test_redact_database_url_hides_the_password() -> None:
    url = "postgresql+psycopg://akbench:akbench_local@127.0.0.1:5959/akbench"
    redacted = redact_database_url(url)
    assert "akbench_local" not in redacted
    assert redacted == "postgresql+psycopg://akbench:***@127.0.0.1:5959/akbench"
    assert redact_database_url("relative/path") == "relative/path"


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
