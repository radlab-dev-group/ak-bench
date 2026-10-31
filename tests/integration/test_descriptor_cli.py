"""CLI behaviour of the descriptor, agent and category command groups."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A scratch project whose descriptors directory mirrors the shipped ones."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(__import__("os").environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _payload(output: str) -> dict:
    return json.loads(output)


def test_help_lists_descriptor_commands(project: Path) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("descriptor", "agent", "category"):
        assert command in result.output


def test_descriptor_validate_reports_each_file(project: Path) -> None:
    result = runner.invoke(app, ["descriptor", "validate", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["failed"] == 0
    assert payload["ok"] == payload["files"]
    assert payload["files"] >= 10
    by_file = {item["file"]: item for item in payload["results"]}
    assert by_file["models/router_models.yaml"]["count"] == 6
    assert all(item["status"] == "ok" for item in payload["results"])


def test_descriptor_validate_fails_on_one_bad_file(project: Path) -> None:
    (project / "descriptors" / "models" / "broken.yaml").write_text(
        'schema_version: "1.0"\nid: broken\nversion: "1.0.0"\nmodel:\n  not_a_field: 1\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["descriptor", "validate", "--json"])
    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["failed"] == 1
    failures = [item for item in payload["results"] if item["status"] == "fail"]
    assert failures[0]["file"] == "models/broken.yaml"
    assert "not_a_field" in failures[0]["error"]
    # the rest of the directory is still reported
    assert payload["ok"] > 0


def test_descriptor_validate_missing_directory_is_an_error(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    result = runner.invoke(app, ["descriptor", "validate", "--json"])
    assert result.exit_code == 1


def test_descriptor_list_json_shape(project: Path) -> None:
    result = runner.invoke(app, ["descriptor", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["count"] == len(payload["descriptors"])
    kinds = {item["kind"] for item in payload["descriptors"]}
    assert {"agent", "model", "metric"} <= kinds
    for item in payload["descriptors"]:
        assert item["digest"].startswith("sha256:")
        assert item["identity"] == f"{item['kind']}:{item['id']}@{item['version']}"


def test_descriptor_list_kind_filter(project: Path) -> None:
    result = runner.invoke(app, ["descriptor", "list", "--kind", "agent", "--json"])
    payload = _payload(result.output)
    assert payload["count"] == 1
    assert payload["descriptors"][0]["id"] == "codex"


def test_descriptor_list_rejects_unknown_kind(project: Path) -> None:
    result = runner.invoke(app, ["descriptor", "list", "--kind", "bogus", "--json"])
    assert result.exit_code == 1
    assert "unknown descriptor kind" in result.output


def test_descriptor_show_agent_with_derived_facts(project: Path) -> None:
    result = runner.invoke(
        app, ["descriptor", "show", "codex", "--kind", "agent", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["id"] == "codex"
    assert payload["capabilities"]["cost_usage"] == {"status": "unsupported", "usable": False}
    assert payload["capabilities"]["token_usage"]["usable"] is True
    assert "model" in payload["controllable_parameters"]


def test_descriptor_show_rejects_missing_reference(project: Path) -> None:
    result = runner.invoke(
        app, ["descriptor", "show", "no-such-agent", "--kind", "agent", "--json"]
    )
    assert result.exit_code == 1
    assert "unknown agent descriptor" in result.output


def test_descriptor_show_dimension_reports_factor_eligibility(project: Path) -> None:
    result = runner.invoke(
        app, ["descriptor", "show", "routed_model", "--kind", "dimension", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["usable_as_factor"] is False
    assert payload["allowed_values"] == []

    result = runner.invoke(
        app, ["descriptor", "show", "model", "--kind", "dimension", "--json"]
    )
    payload = _payload(result.output)
    assert payload["usable_as_factor"] is True
    assert "auto_codex" in payload["allowed_values"]


def test_agent_list_and_inspect(project: Path) -> None:
    result = runner.invoke(app, ["agent", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["count"] == 1
    assert payload["agents"][0]["id"] == "codex"

    result = runner.invoke(app, ["agent", "inspect", "codex", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["descriptor"]["agent"]["adapter"] == "codex_cli"
    assert payload["capabilities"]["workspace_binding"]["usable"] is True


def test_agent_inspect_unknown_fails(project: Path) -> None:
    result = runner.invoke(app, ["agent", "inspect", "nope", "--json"])
    assert result.exit_code == 1
    assert "unknown agent descriptor" in result.output


def test_category_list_marks_enabled_and_disabled(project: Path) -> None:
    result = runner.invoke(app, ["category", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    by_id = {item["id"]: item for item in payload["categories"]}
    assert by_id["bug_fix"]["enabled"] is True
    assert by_id["refactoring"]["enabled"] is False
    assert by_id["new_feature"]["difficulties"] == ["easy", "medium", "hard", "expert"]
