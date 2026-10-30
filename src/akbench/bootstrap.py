"""``akbench init``: create directories, write a config, apply migrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from akbench.config.loader import LoadedConfig, build_app_paths, resolve_database_url
from akbench.config.models import SCHEMA_VERSION
from akbench.core.errors import DatabaseError
from akbench.core.logging_setup import get_logger
from akbench.storage.migrator import schema_status, upgrade

LOG = get_logger("bootstrap")

CONFIG_TEMPLATE = """# AK-Bench default configuration.
# Every value can be overridden by an environment variable:
#   AKBENCH__LOGGING__LEVEL=DEBUG  AKBENCH__DATABASE__URL=sqlite:////tmp/akbench.sqlite
schema_version: {schema_version}

paths:
  data_dir: data
  artifacts_dir: data/artifacts
  workspaces_dir: data/workspaces
  runtime_instances_dir: data/runtime_instances
  reports_dir: reports
  database_file: data/akbench.sqlite
  logs_dir: data/logs

database:
  # url: null means "use paths.database_file as a SQLite file".
  url: null
  echo: false
  timeout_seconds: 30

logging:
  level: INFO
  format: console
  to_file: false
  file: data/logs/akbench.log
  max_bytes: 10000000
  backup_count: 5

doctor:
  # Tool names are configured, never hardcoded in the engine.
  required_tools: [git]
  optional_tools: [docker]
  required_packages: [pydantic, typer, sqlalchemy, alembic, jinja2, yaml]
  min_free_disk_mb: 500
"""


@dataclass
class InitReport:
    config_written: bool = False
    config_path: Path | None = None
    created_dirs: list[Path] = field(default_factory=list)
    database_created: bool = False
    revision_before: str | None = None
    revision_after: str | None = None
    schema_summary: str = ""
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "config_written": self.config_written,
            "config_path": str(self.config_path) if self.config_path else None,
            "created_dirs": [str(path) for path in self.created_dirs],
            "database_created": self.database_created,
            "revision_before": self.revision_before,
            "revision_after": self.revision_after,
            "schema": self.schema_summary,
            "messages": self.messages,
        }


def initialize(
    loaded: LoadedConfig,
    environ: dict[str, str] | None = None,
    *,
    write_config: bool = True,
    migrate: bool = True,
    force_config: bool = False,
) -> InitReport:
    settings = loaded.settings
    paths = build_app_paths(settings, environ)
    report = InitReport()

    report.created_dirs = paths.ensure()
    for directory in report.created_dirs:
        LOG.info("created directory %s", directory)

    config_target = loaded.path or (paths.project_root / "configs" / "defaults.yaml")
    report.config_path = config_target
    if write_config:
        if config_target.exists() and not force_config:
            report.messages.append(f"config already present: {config_target}")
        else:
            config_target.parent.mkdir(parents=True, exist_ok=True)
            config_target.write_text(
                CONFIG_TEMPLATE.format(schema_version=SCHEMA_VERSION), encoding="utf-8"
            )
            report.config_written = True
            LOG.info("wrote config %s", config_target)

    database_url = resolve_database_url(settings, environ)
    database_file = paths.database_file
    report.database_created = not database_file.exists()

    if migrate:
        report.revision_before, report.revision_after = upgrade(database_url)
        LOG.info(
            "migrations applied: %s -> %s",
            report.revision_before or "(none)",
            report.revision_after,
        )

    try:
        report.schema_summary = schema_status(database_url).describe()
    except DatabaseError as exc:  # pragma: no cover - surfaced by doctor
        report.messages.append(f"schema status unavailable: {exc}")

    return report
