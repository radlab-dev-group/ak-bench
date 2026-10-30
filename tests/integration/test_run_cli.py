"""CLI behaviour of ``akbench run single``: one orchestrated run, end to end.

A stub executable named ``codex`` stands in for the agent, so the command, the
descriptor validation, the orchestrator, the workspace manager and the evaluator
are all exercised together without an agent or a network. The command itself
never knows the stub exists.
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
STUB = REPO_ROOT / "tests" / "contract" / "stubs" / "codex_stub.py"
FIXER_STUB = REPO_ROOT / "tests" / "contract" / "stubs" / "codex_fixer_stub.py"
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
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    monkeypatch.setenv("PATH", os.pathsep.join([str(_bin(tmp_path)), os.environ["PATH"]]))
    for name in list(os.environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    return bin_dir


def use_agent(project: Path, source: Path) -> None:
    """Put ``source`` on PATH under the name the agent descriptor requires."""
    target = _bin(project.parent) / "codex"
    shutil.copyfile(source, target)
    target.chmod(target.stat().st_mode | 0o111)


def payload_of(output: str) -> dict:
    return json.loads(output[output.index("{") :])


def test_a_fixing_agent_run_passes_and_is_recorded(project: Path) -> None:
    use_agent(project, FIXER_STUB)

    result = runner.invoke(
        app,
        ["run", "single", "wordcount-001", "--agent", "codex", "--timeout", "60", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = payload_of(result.output)
    assert payload["state"] == "completed"
    assert payload["ok"] is True
    assert payload["task"] == "wordcount-001@1.0.0"
    assert payload["evaluation"]["verdict"] == "passed"
    assert payload["evaluation"]["total"] == 5

    record = Path(payload["record"])
    assert record.is_file()
    recorded = json.loads(record.read_text(encoding="utf-8"))
    states = [event["state"] for event in recorded["history"]]
    assert states[-1] == "completed"
    assert "creating_workspace" in states and "evaluating" in states
    assert Path(recorded["workspace_path"]).name.startswith("wordcount-001-")


def test_an_agent_that_does_nothing_completes_without_passing(project: Path) -> None:
    use_agent(project, STUB)

    result = runner.invoke(
        app, ["run", "single", "wordcount-001", "--agent", "codex", "--json"]
    )

    assert result.exit_code == 1, result.output
    payload = payload_of(result.output)
    assert payload["state"] == "completed"
    assert payload["ok"] is False
    assert payload["evaluation"]["verdict"] in {"partial", "failed"}


def test_the_pristine_repository_passes_without_an_agent(project: Path) -> None:
    """--no-mutation runs the unmutated task, so a no-op agent has nothing to fix."""
    use_agent(project, STUB)

    result = runner.invoke(
        app,
        ["run", "single", "wordcount-001", "--agent", "codex", "--no-mutation", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = payload_of(result.output)
    assert payload["evaluation"]["verdict"] == "passed"


def test_the_workspace_is_removed_only_when_asked(project: Path) -> None:
    use_agent(project, FIXER_STUB)

    kept = runner.invoke(
        app, ["run", "single", "wordcount-001", "--agent", "codex", "--json"]
    )
    assert kept.exit_code == 0, kept.output
    workspace = Path(payload_of(kept.output)["workspace"])
    assert workspace.is_dir()

    removed = runner.invoke(
        app, ["run", "single", "wordcount-001", "--agent", "codex", "--cleanup", "--json"]
    )
    assert removed.exit_code == 0, removed.output
    assert not Path(payload_of(removed.output)["workspace"]).exists()


def test_an_unknown_agent_is_rejected_before_any_work(project: Path) -> None:
    use_agent(project, FIXER_STUB)

    result = runner.invoke(
        app, ["run", "single", "wordcount-001", "--agent", "does-not-exist", "--json"]
    )

    assert result.exit_code == 1
    assert "cannot resolve agent" in result.output
    assert not (project / "data" / "artifacts" / "runs").exists()


def test_an_undeclared_agent_parameter_is_an_invalid_configuration(project: Path) -> None:
    use_agent(project, FIXER_STUB)

    result = runner.invoke(
        app,
        [
            "run",
            "single",
            "wordcount-001",
            "--agent",
            "codex",
            "--param",
            "not_a_real_option=1",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = payload_of(result.output)
    assert payload["state"] == "invalid_configuration"


def test_a_missing_task_is_reported(project: Path) -> None:
    use_agent(project, STUB)

    result = runner.invoke(app, ["run", "single", "no-such-task", "--agent", "codex"])

    assert result.exit_code == 1
    assert "unknown task" in result.output
