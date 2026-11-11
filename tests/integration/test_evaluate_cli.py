"""CLI behaviour of ``akbench evaluate`` against the sample task."""

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
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    shutil.copytree(REPO_ROOT / "datasets", root / "datasets")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(__import__("os").environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _prepare(project: Path, workspace_id: str, mutation: bool) -> Path:
    args = ["dataset", "prepare", "wordcount-001", "--workspace-id", workspace_id]
    if not mutation:
        args.append("--no-mutation")
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return Path(_payload(result.output)["path"])


def _payload(output: str) -> dict:
    return json.loads(output[output.index("{") :])


def test_evaluate_clean_workspace_passes(project: Path) -> None:
    workspace = _prepare(project, "ws-clean", mutation=False)
    result = runner.invoke(
        app, ["evaluate", "task", "wordcount-001", "--workspace", str(workspace), "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["verdict"] == "passed"
    assert payload["total"] == 5
    report = Path(payload["artifacts"]["junit_xml"])
    assert report.name == "junit.xml"
    assert report.is_file()


def test_evaluate_mutated_workspace_fails(project: Path) -> None:
    workspace = _prepare(project, "ws-mutated", mutation=True)
    result = runner.invoke(
        app, ["evaluate", "task", "wordcount-001", "--workspace", str(workspace), "--json"]
    )
    assert result.exit_code == 1, result.output
    payload = _payload(result.output)
    assert payload["verdict"] in {"partial", "failed"}
    assert payload["failed"]
    assert Path(payload["artifacts"]["junit_xml"]).is_file()


def test_evaluate_unknown_task_is_reported(project: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["evaluate", "task", "nope", "--workspace", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "unknown task" in result.output


def test_evaluate_missing_workspace_is_reported(project: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["evaluate", "task", "wordcount-001", "--workspace", str(tmp_path / "missing")],
    )
    assert result.exit_code == 1
    assert "workspace is not a directory" in result.output


def test_evaluate_with_a_reference_patch_scores_the_overlap(project: Path) -> None:
    """`--reference-patch` is how the diff evaluator gets its subject (plan 16)."""
    workspace = _prepare(project, "ws-diff", mutation=True)
    reference = (
        REPO_ROOT / "datasets" / "bug_fix" / "wordcount-001" / "mutations" / "mutation-001.patch"
    )
    result = runner.invoke(
        app,
        [
            "evaluate",
            "task",
            "wordcount-001",
            "--workspace",
            str(workspace),
            "--evaluator",
            "diff_evaluator",
            "--reference-patch",
            str(reference),
            "--json",
        ],
    )
    # A diff never passes, so the CLI leaves 1: the task was not proven solved,
    # which is a normal outcome rather than a broken measurement (exit 2).
    assert result.exit_code == 1, result.output
    payload = _payload(result.output)
    assert payload["evaluator_id"] == "diff_evaluator"
    assert payload["verdict"] == "partial"
    assert payload["score"] == 1.0
    assert payload["details"]["files_matched"] == ["src/wordcount/text.py"]
    assert Path(payload["artifacts"]["produced_diff"]).is_file()


def test_evaluate_with_a_declared_analyser_command(project: Path) -> None:
    """`--command` reaches the static analyser; a clean report is a pass."""
    workspace = _prepare(project, "ws-static", mutation=False)
    result = runner.invoke(
        app,
        [
            "evaluate",
            "task",
            "wordcount-001",
            "--workspace",
            str(workspace),
            "--evaluator",
            "static_analysis_evaluator",
            "--command",
            "python3 -c \"import json; print(json.dumps([]))\"",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["evaluator_id"] == "static_analysis_evaluator"
    assert payload["verdict"] == "passed"
    assert payload["score"] == 1.0


def test_evaluate_a_broken_measurement_exits_two(project: Path, tmp_path: Path) -> None:
    """A supplementary evaluator with no subject is exit 2, never exit 1."""
    workspace = _prepare(project, "ws-noref", mutation=False)
    result = runner.invoke(
        app,
        [
            "evaluate",
            "task",
            "wordcount-001",
            "--workspace",
            str(workspace),
            "--evaluator",
            "diff_evaluator",
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    payload = _payload(result.output)
    assert payload["verdict"] == "evaluator_error"
    assert "reference patch" in payload["details"]["reason"]
