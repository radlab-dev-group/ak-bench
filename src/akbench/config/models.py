"""Pydantic configuration models.

Configuration is YAML-first with ``AKBENCH__SECTION__FIELD`` overrides.
Unknown keys are rejected: a silently ignored option would make an experiment
look configured when it is not (implementation plan, rule 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from akbench.core.errors import ConfigError

SCHEMA_VERSION = 1


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PathsSettings(_StrictModel):
    """Locations relative to the project root unless absolute."""

    data_dir: Path = Path("data")
    artifacts_dir: Path = Path("data/artifacts")
    workspaces_dir: Path = Path("data/workspaces")
    runtime_instances_dir: Path = Path("data/runtime_instances")
    reports_dir: Path = Path("reports")
    descriptors_dir: Path = Path("descriptors")
    datasets_dir: Path = Path("datasets")
    repositories_dir: Path = Path("data/repositories")
    database_file: Path = Path("data/akbench.sqlite")
    logs_dir: Path | None = Path("data/logs")


class PostgresSettings(_StrictModel):
    """Connection parameters of the default PostgreSQL instance.

    These mirror the ``AKBENCH_PG_*`` variables of ``scripts/run-postgres.sh``
    so one ``.env`` file drives both the helper container and the engine.
    """

    host: str = "127.0.0.1"
    port: int = 5959
    user: str = "akbench"
    #: No default, on purpose. A shipped password is a password that every
    #: install of this project shares, and a deployment that never sets
    #: ``AKBENCH_PG_PASSWORD`` would rather have a loud configuration error now
    #: than an guessable credential later.
    #:
    #: A ``SecretStr``, because the settings object is dumped -- ``config show
    #: --json`` serialises the whole thing -- and a plain string field would
    #: carry the database password into whatever that output is pasted into.
    password: SecretStr | None = None
    database: str = "akbench"
    #: One imported SQLite history per schema (`akbench migrate`), read back by
    #: naming it here. ``None`` is the server's default schema.
    namespace: str | None = None


class DatabaseSettings(_StrictModel):
    """Where recorded benchmarks live.

    ``backend`` picks the engine; ``url`` overrides both and is how a
    fully-formed SQLAlchemy URL is pinned (a test database, a managed
    instance). SQLite stays selectable because a benchmark has to run on a
    laptop without a server.
    """

    backend: Literal["postgres", "sqlite"] = "postgres"
    url: str | None = None
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    echo: bool = False
    timeout_seconds: int = 30

    @field_validator("url")
    @classmethod
    def _check_scheme(cls, value: str | None) -> str | None:
        if value and "://" not in value:
            raise ValueError("database.url must be a SQLAlchemy URL (e.g. sqlite:///...)")
        return value

    @property
    def postgres_url(self) -> str:
        """SQLAlchemy URL of the configured PostgreSQL instance (psycopg3 driver).

        Raises where it is used rather than at import or validation time, because
        the absence of a password is only a problem at the moment someone tries
        to connect with it.
        """
        from urllib.parse import quote

        if self.postgres.password is None:
            raise ConfigError(
                "database.postgres.password is not set, and there is no default "
                "to fall back on: export AKBENCH_PG_PASSWORD "
                "(scripts/run-postgres.sh reads the same name)"
            )
        password = self.postgres.password.get_secret_value()
        return (
            "postgresql+psycopg://"
            f"{quote(self.postgres.user, safe="")}:{quote(password, safe="")}"
            f"@{self.postgres.host}:{self.postgres.port}/{self.postgres.database}"
        )


class LoggingSettings(_StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["console", "json"] = "console"
    to_file: bool = False
    file: Path | None = Path("data/logs/akbench.log")
    max_bytes: int = 10_000_000
    backup_count: int = 5


class DoctorSettings(_StrictModel):
    """Environment expectations checked by ``akbench doctor``.

    Tool names are configured, never hardcoded, so the engine stays free of
    knowledge about any particular agent (implementation plan, rule 3).
    """

    required_tools: list[str] = Field(default_factory=lambda: ["git"])
    optional_tools: list[str] = Field(default_factory=lambda: ["docker"])
    required_packages: list[str] = Field(
        default_factory=lambda: ["pydantic", "typer", "sqlalchemy", "alembic", "jinja2", "yaml"]
    )
    min_free_disk_mb: int = 500


class Settings(_StrictModel):
    schema_version: int = SCHEMA_VERSION
    project_root: Path | None = None
    paths: PathsSettings = Field(default_factory=PathsSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    doctor: DoctorSettings = Field(default_factory=DoctorSettings)

    @field_validator("schema_version")
    @classmethod
    def _check_schema(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported config schema_version {value!r}, expected {SCHEMA_VERSION}"
            )
        return value
