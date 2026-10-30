"""Pydantic configuration models.

Configuration is YAML-first with ``AKBENCH__SECTION__FIELD`` overrides.
Unknown keys are rejected: a silently ignored option would make an experiment
look configured when it is not (implementation plan, rule 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    database_file: Path = Path("data/akbench.sqlite")
    logs_dir: Path | None = Path("data/logs")


class DatabaseSettings(_StrictModel):
    url: str | None = None
    echo: bool = False
    timeout_seconds: int = 30

    @field_validator("url")
    @classmethod
    def _check_scheme(cls, value: str | None) -> str | None:
        if value and "://" not in value:
            raise ValueError("database.url must be a SQLAlchemy URL (e.g. sqlite:///...)")
        return value


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
