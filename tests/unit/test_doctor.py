from __future__ import annotations

from pathlib import Path

from akbench.config.loader import load_settings
from akbench.doctor import (
    CheckStatus,
    check_directories,
    check_disk,
    check_packages,
    check_python,
    check_tools,
    run_diagnostics,
)

MARKER = "[project]\nname = \"ak-bench\"\n"


def _load(project: Path, environ: dict[str, str]):
    return load_settings(None, project_root=project, environ=environ)


def test_python_check_passes() -> None:
    assert check_python().status is CheckStatus.OK


def test_package_check_accepts_import_and_distribution_names() -> None:
    results = check_packages(["yaml", "PyYAML", "pydantic", "definitely-not-installed-xyz"])
    by_name = {result.name: result.status for result in results}
    assert by_name["package:yaml"] is CheckStatus.OK
    assert by_name["package:PyYAML"] is CheckStatus.OK
    assert by_name["package:pydantic"] is CheckStatus.OK
    assert by_name["package:definitely-not-installed-xyz"] is CheckStatus.FAIL


def test_missing_directory_fails(tmp_path: Path) -> None:
    result = check_directories([tmp_path / "absent"])[0]
    assert result.status is CheckStatus.FAIL
    assert "init" in (result.hint or "")


def test_tools_split_required_and_optional() -> None:
    required = check_tools(["definitely-not-a-tool-xyz"], required=True)[0]
    optional = check_tools(["definitely-not-a-tool-xyz"], required=False)[0]
    assert required.status is CheckStatus.FAIL
    assert optional.status is CheckStatus.INFO


def test_disk_check_reports_configured_minimum(tmp_path: Path) -> None:
    assert check_disk(tmp_path, 1).status is CheckStatus.OK
    assert check_disk(tmp_path, 10**12).status is CheckStatus.WARNING


def test_diagnostics_fail_without_init(project_dir: Path, empty_environ: dict[str, str]) -> None:
    report = run_diagnostics(_load(project_dir, empty_environ), environ=empty_environ)
    names = {check.name: check.status for check in report.checks}
    assert names["dir:data"] is CheckStatus.FAIL
    assert names["schema"] is CheckStatus.FAIL
    assert not report.ok


def test_diagnostics_pass_after_init(project_dir: Path, empty_environ: dict[str, str]) -> None:
    from akbench.bootstrap import initialize

    loaded = _load(project_dir, empty_environ)
    initialize(loaded, environ=empty_environ, write_config=False)

    report = run_diagnostics(loaded, environ=empty_environ)
    assert report.ok, [(c.name, c.status, c.detail) for c in report.checks if c.status.blocks]
    assert {c.name: c.status for c in report.checks}["schema"] is CheckStatus.OK


def test_schema_behind_head_is_reported(project_dir: Path, empty_environ: dict[str, str]) -> None:
    """A database with only some of the tables must not look like a valid schema."""
    from akbench.config.loader import resolve_database_url
    from akbench.storage.db import create_db_engine
    from akbench.storage.models import Base

    loaded = _load(project_dir, empty_environ)
    url = resolve_database_url(loaded.settings, environ=empty_environ)
    (project_dir / "data").mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(url)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["experiments"]])
    engine.dispose()

    report = run_diagnostics(_load(project_dir, empty_environ), environ=empty_environ)
    statuses = {check.name: check.status for check in report.checks}
    assert statuses["schema"] is CheckStatus.FAIL


def test_report_as_dict_shape(project_dir: Path, empty_environ: dict[str, str]) -> None:
    report = run_diagnostics(_load(project_dir, empty_environ), environ=empty_environ)
    payload = report.as_dict()
    assert payload["ok"] is report.ok
    assert payload["summary"]["checks"] == len(report.checks)
    assert isinstance(payload["checks"], list)
    assert {"name", "status", "detail"} <= set(payload["checks"][0])
