"""The export CLI: one experiment out as JSON, CSV and HTML, screened.

A stored run (stub agent) must become an export whose files exist, whose JSON
parses, whose CSV has one row per run, and whose contents do not carry
anything that must not leave the machine.
"""

from __future__ import annotations

import csv
import io
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
        [
            "run", "single", "wordcount-001",
            "--agent", "codex", "--timeout", "60", "--store", "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert isinstance(payload, dict)
    return payload["stored"]


def test_export_writes_all_three_formats(project: Path) -> None:
    stored = _store_run(project)
    uid = str(stored["experiment_uid"])

    result = runner.invoke(app, ["export", "experiment", uid, "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    target = Path(payload["output"])
    assert (target / f"{uid}.json").is_file()
    assert (target / f"{uid}.runs.csv").is_file()
    assert (target / f"{uid}.html").is_file()

    document = json.loads((target / f"{uid}.json").read_text(encoding="utf-8"))
    assert document["experiment"]["uid"] == uid
    assert len(document["runs"]) == 1

    csv_text = (target / f"{uid}.runs.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(rows) == 1
    assert rows[0]["run_uid"] == str(stored["run_uid"])


def test_export_of_one_format_only(project: Path) -> None:
    stored = _store_run(project)
    uid = str(stored["experiment_uid"])

    result = runner.invoke(app, ["export", "experiment", uid, "--format", "csv", "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    names = {Path(path).name for path in payload["files"]}
    # the ad-hoc uid contains a slash; the file keeps the flat form
    assert names == {f"{Path(uid).name}.runs.csv"}


def test_export_of_an_unknown_experiment_fails(project: Path) -> None:
    _store_run(project)

    result = runner.invoke(app, ["export", "experiment", "ghost@9.9.9"])
    assert result.exit_code == 1
    assert "unknown experiment" in result.output


def test_export_redacts_a_secret_environment_value(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_ROUTER_API_KEY", "ROUTERSECRETVALUE42")
    _store_run(project)
    uid = next(
        str(item["uid"])
        for item in _json(runner.invoke(app, ["history", "experiments", "--json"]).output)
    )

    result = runner.invoke(app, ["export", "experiment", uid, "--format", "json", "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    body = (Path(payload["output"]) / f"{uid}.json").read_text(encoding="utf-8")
    assert "ROUTERSECRETVALUE42" not in body
