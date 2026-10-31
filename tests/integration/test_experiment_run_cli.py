"""``akbench experiment run``: a whole matrix, executed and recorded.

The stub agent stands in for Codex, so the matrix, the orchestrator, the
evaluator and the history all run together. The point of these tests is the
whole point of the project: from one YAML file to runs recorded in the history
to a report, with nothing invented on the way.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB = REPO_ROOT / "tests" / "contract" / "stubs" / "codex_fixer_stub.py"
EXPERIMENTS = REPO_ROOT / "configs" / "experiments"
runner = CliRunner()


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "ak-bench"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    shutil.copytree(REPO_ROOT / "datasets", root / "datasets")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
    (root / "bin").mkdir()
    stub = root / "bin" / "codex"
    shutil.copyfile(STUB, stub)
    stub.chmod(stub.stat().st_mode | 0o111)
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    monkeypatch.setenv("PATH", os.pathsep.join([str(root / "bin"), os.environ["PATH"]]))
    for name in list(os.environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _json(output: str) -> object:
    decoder = json.JSONDecoder()
    starts = [index for index in (output.find("["), output.find("{")) if index != -1]
    assert starts, f"no JSON in output: {output[:200]!r}"
    payload, _ = decoder.raw_decode(output[min(starts) :])
    return payload


def test_an_experiment_matrix_runs_and_reports_each_run(project: Path) -> None:
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert isinstance(payload, dict)
    # 1 task x 1 variant x 2 repetitions
    assert payload["planned"] == 2
    assert payload["completed"] == 2
    assert {run["state"] for run in payload["runs"]} == {"completed"}


def test_runs_of_an_experiment_land_in_the_history_and_the_report(project: Path) -> None:
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"
    runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--json"])

    experiments = _json(runner.invoke(app, ["history", "experiments", "--json"]).output)
    row = next(item for item in experiments if item["uid"] == "wordcount-direct-sanity@1.0.0")
    assert row["runs"] == 2
    assert row["descriptor"] == "wordcount-direct-sanity@1.0.0"

    report = runner.invoke(app, ["report", "all", "--json"])
    assert report.exit_code == 0, report.output
    payload = _json(report.output)
    index = Path(payload["output"]) / "index.html"
    assert index.is_file()
    assert "wordcount-direct-sanity@1.0.0" in index.read_text(encoding="utf-8")


def test_only_limits_the_matrix_without_losing_the_plan(project: Path) -> None:
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"

    result = runner.invoke(
        app, ["experiment", "run", str(experiment), "--store", "--only", "1", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert payload["completed"] == 1
    assert payload["planned"] == 2

    runs = _json(runner.invoke(app, ["history", "runs", "--json"]).output)
    assert len(runs) == 1
    assert runs[0]["repetition"] == 1


def test_an_unrunnable_experiment_is_refored_before_any_run(project: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text(
        """
schema_version: "1.0"
id: broken
version: "1.0.0"
title: A broken experiment
experiment:
  type: configuration
  agent: {id: ghost, version: "1.0.0"}
  execution: {mode: direct}
  dataset: {filters: {task_ids: [wordcount-001]}}
  factors: {strategy: full_factorial}
  execution_policy: {repetitions: 1}
  evaluation: {evaluators: [pytest_evaluator]}
  metrics: [task_success_rate]
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "run", str(broken)])

    assert result.exit_code == 1
    assert "not runnable" in result.output
