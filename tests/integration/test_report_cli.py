"""The report CLI: what the recorded history becomes when it is written out.

A stored run (stub agent standing in for the real one) must produce a report
tree a reader can open: the dashboard, the experiment page, the task page and
the comparison pages, all linked, all escaping what the agent wrote.
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


def _store_run(project: Path) -> dict:
    result = runner.invoke(
        app,
        ["run", "single", "wordcount-001", "--agent", "codex", "--timeout", "60",
         "--store", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert isinstance(payload, dict)
    return payload["stored"]


def test_report_all_writes_the_full_tree(project: Path) -> None:
    stored = _store_run(project)

    result = runner.invoke(app, ["report", "all", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert isinstance(payload, dict)
    assert payload["runs"] == 1
    target = Path(payload["output"])

    for relative in (
        "index.html",
        "assets/style.css",
        "tasks/index.html",
        "agents/index.html",
        "runtimes/index.html",
        "plugins/index.html",
        "models/index.html",
    ):
        assert (target / relative).is_file(), relative
    assert (target / "experiments" / str(stored["experiment_uid"]) / "index.html").is_file()

    index = (target / "index.html").read_text(encoding="utf-8")
    assert str(stored["experiment_uid"]) in index
    assert 'href="assets/style.css"' in index


def test_report_experiment_writes_one_page(project: Path) -> None:
    stored = _store_run(project)
    uid = str(stored["experiment_uid"])

    result = runner.invoke(app, ["report", "experiment", uid, "--json"])
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    page = Path(payload["report"])
    assert page.is_file()
    body = page.read_text(encoding="utf-8")
    assert str(stored["run_uid"]) in body
    assert "Artifacts" in body
    assert "Pinned descriptors" in body


def test_report_of_an_unknown_experiment_fails(project: Path) -> None:
    _store_run(project)

    result = runner.invoke(app, ["report", "experiment", "ghost@9.9.9"])
    assert result.exit_code == 1
    assert "unknown experiment" in result.output


def test_report_of_an_unknown_task_fails(project: Path) -> None:
    _store_run(project)

    result = runner.invoke(app, ["report", "task", "ghost-999@9.9.9"])
    assert result.exit_code == 1
    assert "unknown task" in result.output


def test_report_task_writes_the_page(project: Path) -> None:
    _store_run(project)

    result = runner.invoke(app, ["report", "task", "wordcount-001@1.0.0", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    page = Path(payload["report"])
    assert page.is_file()
    assert "wordcount-001@1.0.0" in page.read_text(encoding="utf-8")


def test_report_on_an_empty_database_is_a_hint_not_a_crash(project: Path) -> None:
    database = project / "data" / "akbench.sqlite"
    if database.exists():
        database.unlink()

    result = runner.invoke(app, ["report", "all"])
    assert result.exit_code == 1
    assert "akbench init" in result.output
