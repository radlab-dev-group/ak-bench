"""CLI behaviour: exit codes, JSON output, init/doctor interaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench import __version__
from akbench.cli.main import app
from akbench.storage.migrator import schema_status

runner = CliRunner()


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(__import__("os").environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _payload(output: str) -> dict:
    return json.loads(output)


def test_help_lists_phase_one_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "init", "doctor", "config"):
        assert command in result.output


def test_version_flag_on_callback() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_command_json() -> None:
    result = runner.invoke(app, ["version", "--json"])
    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ak_bench"] == __version__
    assert payload["dependencies"]["pydantic"]


def test_init_creates_layout_config_and_schema(project: Path) -> None:
    result = runner.invoke(app, ["init", "--json"])
    assert result.exit_code == 0, result.output

    payload = _payload(result.output)
    db_url = f"sqlite:///{project / 'data' / 'akbench.sqlite'}"
    assert payload["revision_after"] == schema_status(db_url).head
    assert Path(payload["config_path"]).is_file()
    assert (project / "data" / "akbench.sqlite").is_file()
    for directory in ("artifacts", "workspaces", "runtime_instances"):
        assert (project / "data" / directory).is_dir()
    assert (project / "reports").is_dir()


def test_init_is_idempotent_and_keeps_config(project: Path) -> None:
    assert runner.invoke(app, ["init", "--json"]).exit_code == 0
    config = project / "configs" / "defaults.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\n# kept\n", encoding="utf-8")

    second = runner.invoke(app, ["init", "--json"])
    assert second.exit_code == 0
    assert "# kept" in config.read_text(encoding="utf-8")
    assert _payload(second.output)["config_written"] is False


def test_doctor_fails_before_init(project: Path) -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["ok"] is False
    failures = {check["name"] for check in payload["checks"] if check["status"] == "fail"}
    assert {"dir:data", "schema"} <= failures


def test_doctor_passes_after_init(project: Path) -> None:
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert _payload(result.output)["ok"] is True


def test_doctor_json_reports_migrations_behind_head(project: Path) -> None:
    from akbench.storage.migrator import downgrade, upgrade

    assert runner.invoke(app, ["init"]).exit_code == 0
    url = f"sqlite:///{project / 'data' / 'akbench.sqlite'}"
    upgrade(url)
    downgrade(url, "base")

    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    statuses = {check["name"]: check["status"] for check in _payload(result.output)["checks"]}
    assert statuses["schema"] == "fail"


def test_config_validate_rejects_unknown_key(project: Path) -> None:
    config = project / "broken.yaml"
    config.write_text("not_a_section: 1\n", encoding="utf-8")

    result = runner.invoke(app, ["--config", str(config), "config", "validate"])
    assert result.exit_code == 1
    assert "not_a_section" in result.output


def test_config_show_json_reports_sources_and_paths(project: Path) -> None:
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["source"].startswith("builtin_defaults")
    assert payload["resolved_paths"]["data_dir"] == str(project / "data")
    assert payload["database_url"].endswith("data/akbench.sqlite")


def test_env_override_is_visible_in_config_show(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AKBENCH__LOGGING__LEVEL", "DEBUG")
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    assert _payload(result.output)["settings"]["logging"]["level"] == "DEBUG"
