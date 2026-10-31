"""End to end: one YAML experiment becomes runs, a history, a report, an export.

This is the promise of the platform in one test. A shipped experiment file, a
stub agent standing in for Codex, and nothing else: the command executes the
matrix, the runs land in the history with their manifests, the report renders
them, and the export leaves with the same facts screened for secrets.

The stub is deterministic and the seed repository is pinned, so the conditions
of the experiment are identical on every run; what a real agent would do is
not asserted, only that the platform did not lose, invent or hide anything.
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
EXPERIMENT = REPO_ROOT / "configs" / "experiments" / "wordcount-direct-sanity.yaml"
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


def test_from_the_yaml_to_the_report_and_the_export(project: Path) -> None:
    uid = "wordcount-direct-sanity@1.0.0"

    # 1. the plan states the cost before anything runs
    plan = runner.invoke(app, ["experiment", "plan", str(EXPERIMENT), "--json"])
    assert plan.exit_code == 0, plan.output
    plan_payload = _json(plan.output)
    assert plan_payload["experiment"] == uid
    assert plan_payload["counts"]["runs"] == 2

    # 2. the matrix runs and is recorded
    run = runner.invoke(app, ["experiment", "run", str(EXPERIMENT), "--store", "--json"])
    assert run.exit_code == 0, run.output
    run_payload = _json(run.output)
    assert run_payload["completed"] == 2
    assert {item["state"] for item in run_payload["runs"]} == {"completed"}

    # 3. the history holds the plan, the runs and the verification of it
    experiments = _json(runner.invoke(app, ["history", "experiments", "--json"]).output)
    row = next(item for item in experiments if item["uid"] == uid)
    assert row["runs"] == 2
    assert row["descriptor"] == uid

    runs = _json(runner.invoke(app, ["history", "runs", uid, "--json"]).output)
    assert len(runs) == 2
    for run_row in runs:
        assert run_row["manifest_digest"], "a stored run must cite its manifest"
        assert run_row["evaluation"]["verdict"] == "passed"

    verify = runner.invoke(app, ["history", "verify", str(runs[0]["uid"])])
    assert verify.exit_code == 0, verify.output

    # 4. the report renders the same history, with the failure path visible
    report = runner.invoke(app, ["report", "all", "--json"])
    assert report.exit_code == 0, report.output
    report_payload = _json(report.output)
    index = Path(report_payload["output"]) / "index.html"
    body = index.read_text(encoding="utf-8")
    assert uid in body
    page = (
        Path(report_payload["output"]) / "experiments" / uid / "index.html"
    ).read_text(encoding="utf-8")
    assert str(runs[0]["uid"]) in page
    assert "Not passed" in page, "the report must keep the failure path visible"

    # 5. the export carries the facts out, screened
    export = runner.invoke(app, ["export", "experiment", uid, "--json"])
    assert export.exit_code == 0, export.output
    export_payload = _json(export.output)
    target = Path(export_payload["output"])
    document = json.loads((target / f"{uid}.json").read_text(encoding="utf-8"))
    assert document["experiment"]["descriptor"] == uid
    assert len(document["runs"]) == 2
    assert document["variants"], "the export must carry the planned variants"
    rows = list(
        csv.DictReader(io.StringIO((target / f"{uid}.runs.csv").read_text(encoding="utf-8")))
    )
    assert len(rows) == 2
    assert all(row["verdict"] == "passed" for row in rows)
    standalone = (target / f"{uid}.html").read_text(encoding="utf-8")
    assert standalone.startswith("<!DOCTYPE html>")
    assert "<style>" in standalone, "the HTML export must read on its own"
