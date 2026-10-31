"""CLI behaviour of the agent command group: list/inspect plus a stubbed run.

The run tests put a stub executable named ``codex`` on PATH and drive the
command end to end, so the CLI, the descriptor validation, the catalog and the
adapter are all exercised without an agent or a network. The runner code has no
knowledge of the stub — it only speaks the contract.
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
runner = CliRunner()


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    shutil.copytree(REPO_ROOT / "datasets", root / "datasets")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "codex"
    shutil.copyfile(STUB, stub)
    stub.chmod(stub.stat().st_mode | 0o111)

    monkeypatch.setenv("AKBENCH_HOME", str(root))
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ["PATH"]]))
    for name in list(os.environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _payload(output: str) -> dict:
    """Extract the JSON document; the runner may prefix human lines to stdout."""
    start = output.index("{")
    return json.loads(output[start:])


def test_agent_list_shows_codex(project: Path) -> None:
    result = runner.invoke(app, ["agent", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert any(agent["id"] == "codex" for agent in payload["agents"])


def test_agent_inspect_reports_capabilities(project: Path) -> None:
    result = runner.invoke(app, ["agent", "inspect", "codex", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["id"] == "codex"
    assert payload["capabilities"]["token_usage"]["status"] == "verified"
    assert payload["capabilities"]["cost_usage"]["status"] == "unsupported"


def test_agent_run_completes_with_the_stub(project: Path, tmp_path: Path) -> None:
    task_file = tmp_path / "task.txt"
    task_file.write_text("Write proof.txt containing akbench ok.", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = runner.invoke(
        app,
        [
            "agent",
            "run",
            "codex",
            "--task-file", str(task_file),
            "--workspace", str(workspace),
            "--param", "sandbox_mode=read-only",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["agent"] == "codex"
    assert payload["status"] == "completed"
    assert payload["workspace"] == str(workspace)
    assert payload["observations"]["session_id"]
    assert payload["observations"]["cost"] is None


def test_agent_run_prepares_the_task_workspace(project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "run",
            "codex",
            "--task", "wordcount-001",
            "--param", "sandbox_mode=workspace-write",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["status"] == "completed"
    assert payload["workspace_provenance"]["task_uid"] == "wordcount-001@1.0.0"
    assert payload["workspace_provenance"]["mutation_applied"] is True


def test_agent_run_rejects_unknown_agent(project: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "agent", "run", "nope",
            "--task-file", str(tmp_path / "t.txt"),
            "--workspace", str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "cannot resolve agent" in result.output


def test_agent_run_rejects_undeclared_parameter(project: Path, tmp_path: Path) -> None:
    task_file = tmp_path / "t.txt"
    task_file.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = runner.invoke(
        app,
        [
            "agent", "run", "codex",
            "--task-file", str(task_file),
            "--workspace", str(workspace),
            "--param", "not_a_real_option=1",
        ],
    )
    assert result.exit_code == 1
    assert "unknown configuration parameter" in result.output


def test_agent_run_requires_a_source(project: Path) -> None:
    result = runner.invoke(app, ["agent", "run", "codex"])
    assert result.exit_code == 1
    assert "provide --workspace or --task" in result.output


def test_agent_run_unknown_runtime_is_refused(project: Path, tmp_path: Path) -> None:
    task_file = tmp_path / "t.txt"
    task_file.write_text("x", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = runner.invoke(
        app,
        [
            "agent", "run", "codex",
            "--task-file", str(task_file),
            "--workspace", str(workspace),
            "--runtime", "does-not-exist",
        ],
    )
    assert result.exit_code == 1
    assert "execution mode is not usable" in result.output
