"""Tests for workspace solution and trace packaging."""

from __future__ import annotations

import zipfile
from pathlib import Path

from akbench.orchestration.packaging import (
    collect_and_package_artifacts,
    pack_agent_traces,
    pack_evaluation_results,
    pack_solution_diff,
    pack_solution_workspace,
)


def test_pack_solution_workspace_filters_excluded_dirs_and_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (workspace / "src" / "main.pyc").write_bytes(b"\x00\x01\x02")

    # Excluded dirs
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("git\n", encoding="utf-8")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "cached.pyc").write_bytes(b"cached")
    (workspace / ".venv").mkdir()
    (workspace / ".venv" / "bin").mkdir()
    (workspace / ".venv" / "bin" / "python").write_text("bin", encoding="utf-8")

    zip_out = tmp_path / "solution.zip"
    created = pack_solution_workspace(workspace, zip_out)

    assert created is not None
    assert created.is_file()

    with zipfile.ZipFile(created, "r") as zf:
        namelist = zf.namelist()
        assert "src/main.py" in namelist
        assert "src/main.pyc" not in namelist
        assert ".git/config" not in namelist
        assert "__pycache__/cached.pyc" not in namelist
        assert ".venv/bin/python" not in namelist


def test_pack_agent_traces(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_stdout.jsonl").write_text('{"line": 1}\n', encoding="utf-8")
    (artifacts_dir / "agent_trace.jsonl").write_text('{"event": "start"}\n', encoding="utf-8")
    (artifacts_dir / "other.txt").write_text("ignored", encoding="utf-8")

    zip_out = tmp_path / "agent_traces.zip"
    created = pack_agent_traces(artifacts_dir, zip_out)

    assert created is not None
    with zipfile.ZipFile(created, "r") as zf:
        namelist = zf.namelist()
        assert "agent_stdout.jsonl" in namelist
        assert "agent_trace.jsonl" in namelist
        assert "other.txt" not in namelist


def test_pack_evaluation_results(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    (eval_dir / "evaluation.json").write_text('{"score": 1.0}\n', encoding="utf-8")
    (eval_dir / "junit.xml").write_text("<testsuites></testsuites>\n", encoding="utf-8")

    zip_out = tmp_path / "evaluation.zip"
    created = pack_evaluation_results(eval_dir, zip_out)

    assert created is not None
    with zipfile.ZipFile(created, "r") as zf:
        namelist = zf.namelist()
        assert "evaluation.json" in namelist
        assert "junit.xml" in namelist


def test_collect_and_package_artifacts(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "file.txt").write_text("content", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_trace.jsonl").write_text("trace", encoding="utf-8")

    eval_dir = artifacts / "evaluation"
    eval_dir.mkdir()
    (eval_dir / "evaluation.json").write_text("{}", encoding="utf-8")

    created = collect_and_package_artifacts(ws, artifacts, eval_dir)
    names = [p.name for p in created]

    assert "solution.zip" in names
    assert "agent_traces.zip" in names
    assert "evaluation.zip" in names
