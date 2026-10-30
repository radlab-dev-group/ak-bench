"""CLI behaviour of the dataset command group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    import shutil

    shutil.copytree(REPO_ROOT / "datasets", root / "datasets")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(__import__("os").environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _payload(output: str) -> dict:
    return json.loads(output)


def test_help_lists_dataset_commands(project: Path) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dataset" in result.output


def test_dataset_list_json_shape(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["count"] == 1
    task = payload["tasks"][0]
    assert task["id"] == "wordcount-001"
    assert task["category"] == "bug_fix"
    assert task["digest"].startswith("sha256:")


def test_dataset_list_category_filter(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "list", "--category", "bug_fix", "--json"])
    assert _payload(result.output)["count"] == 1
    result = runner.invoke(app, ["dataset", "list", "--category", "nope", "--json"])
    assert _payload(result.output)["count"] == 0


def test_dataset_validate_reports_ok(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "validate", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["tasks"] == 1


def test_dataset_validate_fails_on_broken_task(project: Path) -> None:
    hidden = project / "datasets" / "bug_fix" / "wordcount-001" / "hidden_tests"
    for child in hidden.iterdir():
        child.unlink()
    result = runner.invoke(app, ["dataset", "validate", "--json"])
    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["ok"] is False
    assert any("hidden tests" in issue for issue in payload["results"][0]["issues"])


def test_dataset_validate_verifies_mutation(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "validate", "--verify-mutations", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    checks = payload["results"][0]["checks"]
    assert checks["mutation_verified"] == "verified"


def test_dataset_show_json_shape(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "show", "wordcount-001", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["id"] == "wordcount-001"
    assert payload["repository"]["ref"] == "HEAD"
    assert payload["repository"]["kind"] == "seed"
    assert payload["mutation"]["patch"] == "mutations/mutation-001.patch"


def test_dataset_show_unknown_fails(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "show", "nope", "--json"])
    assert result.exit_code == 1
    assert "unknown task" in result.output


def test_dataset_prepare_creates_and_reports(project: Path) -> None:
    result = runner.invoke(
        app, ["dataset", "prepare", "wordcount-001", "--workspace-id", "cli-demo", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["mutation_applied"] is True
    assert Path(payload["path"]).is_dir()
    assert payload["fingerprint"].startswith("sha256:")
    # clean up so the test leaves no workspace behind
    import shutil

    shutil.rmtree(payload["path"], ignore_errors=True)


def test_dataset_prepare_no_mutation(project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "dataset",
            "prepare",
            "wordcount-001",
            "--workspace-id",
            "cli-base",
            "--no-mutation",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["mutation_applied"] is False
    import shutil

    shutil.rmtree(payload["path"], ignore_errors=True)
