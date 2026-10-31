"""The history CLI: what running an experiment leaves behind, read back.

The plan is stored through ``experiment plan --store`` and a run through
``run single --store`` (a stub agent stands in for the real one); the history
commands then report them. ``history verify`` is the one worth proving end to
end: it must catch an artifact that was changed after the run.
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


def test_a_stored_run_is_readable_back_through_the_history(project: Path) -> None:
    stored = _store_run(project)

    experiments = _json(runner.invoke(app, ["history", "experiments", "--json"]).output)
    assert isinstance(experiments, list)
    assert any(item["uid"] == stored["experiment_uid"] for item in experiments)

    run = _json(
        runner.invoke(app, ["history", "show", str(stored["run_uid"]), "--json"]).output
    )
    assert isinstance(run, dict)
    assert run["status"] == "completed"
    assert run["evaluation"]["verdict"] == "passed"
    assert run["manifest_digest"] == stored["manifest_digest"]


def test_verify_passes_and_catches_a_tampered_artifact(project: Path) -> None:
    stored = _store_run(project)
    run_uid = str(stored["run_uid"])

    ok = runner.invoke(app, ["history", "verify", run_uid])
    assert ok.exit_code == 0, ok.output

    run = _json(runner.invoke(app, ["history", "show", run_uid, "--json"]).output)
    assert isinstance(run, dict)
    artifacts = run["artifacts"]
    assert artifacts, "a stored run must have artifacts to verify"
    target = next(Path(item["path"]) for item in artifacts if item["kind"] == "junit")
    target.write_text(target.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")

    bad = runner.invoke(app, ["history", "verify", run_uid])
    assert bad.exit_code == 1
    assert "mismatch" in bad.output


def test_planning_with_store_records_the_plan_and_its_snapshots(project: Path) -> None:
    result = runner.invoke(
        app,
        ["experiment", "plan", str(EXPERIMENTS / "knowledge-on-off.yaml"), "--store", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    stored = payload["stored"]
    assert stored["variants"] >= 1
    assert stored["snapshots"] >= 1

    experiments = _json(runner.invoke(app, ["history", "experiments", "--json"]).output)
    row = next(item for item in experiments if item["uid"] == stored["experiment_uid"])
    assert row["descriptor"] is not None
    assert row["runs"] == 0

    events = _json(runner.invoke(app, ["history", "runs", "--json"]).output)
    assert events == []


def test_history_reports_an_unmigrated_database_as_a_hint_not_a_crash(project: Path) -> None:
    (project / "data" / "akbench.sqlite").unlink() if (project / "data").exists() else None
    result = runner.invoke(app, ["history", "experiments"])

    assert result.exit_code == 1
    assert "akbench init" in result.output
