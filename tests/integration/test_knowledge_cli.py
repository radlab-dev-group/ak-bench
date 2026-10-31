"""CLI behaviour of ``akbench knowledge``: plan and readiness.

These tests also guard the shipped memory experiment: a definition that stops
planning is a broken promise, not a later test failure. The assertions here
are the comparison rules in action — the replay and the fresh arm share a
fingerprint, the gate is visible, and an unconfirmed knowledge base is never
read as a ready one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "configs" / "experiments" / "knowledge-replay.yaml"
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
    (root / "configs" / "experiments").mkdir(parents=True)
    shutil.copy(EXAMPLE, root / "configs" / "experiments" / "knowledge-replay.yaml")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(__import__("os").environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _payload(output: str) -> dict | list:
    decoder = json.JSONDecoder()
    starts = [index for index in (output.find("["), output.find("{")) if index != -1]
    assert starts, f"no JSON in output: {output[:200]!r}"
    return decoder.raw_decode(output[min(starts) :])[0]


def test_plan_json_carries_arms_fingerprints_and_gate(project: Path) -> None:
    result = runner.invoke(app, ["knowledge", "plan", "--json"])

    assert result.exit_code == 0, result.output
    plan = _payload(result.output)[0]

    assert plan["validation"]["ok"] is True
    assert plan["plugin"] == "agentic_knowledge"
    assert [arm["mode"] for arm in plan["learning"]] == ["learning"]
    assert [arm["mode"] for arm in plan["arms"]] == ["replay", "fresh"]

    replay, fresh = plan["arms"]
    assert replay["fingerprint"]["digest"] == fresh["fingerprint"]["digest"]
    assert replay["knowledge_access"] == {"read": True, "write": False}
    assert fresh["knowledge_access"] == {"read": False, "write": False}
    assert replay["gate"]["blocked"] is True
    assert "gate" not in fresh
    assert replay["depends_on"] == plan["learning_session"]["session_id"]


def test_plan_human_output_names_the_gate(project: Path) -> None:
    result = runner.invoke(app, ["knowledge", "plan"])

    assert result.exit_code == 0, result.output
    assert "scenario" in result.output
    assert "gate=blocked" in result.output
    assert "namespace=supported" in result.output


def test_allow_unverified_releases_the_gate(project: Path) -> None:
    result = runner.invoke(
        app, ["knowledge", "plan", "--allow-unverified", "--json"]
    )

    assert result.exit_code == 0, result.output
    plan = _payload(result.output)[0]
    replay = next(arm for arm in plan["arms"] if arm["mode"] == "replay")
    assert replay["gate"]["allowed"] is True
    assert replay["gate"]["allow_unverified"] is True
    assert replay["gate"]["evidence_grade"] == "unverified"


def test_readiness_reports_what_the_deployment_cannot_confirm(project: Path) -> None:
    result = runner.invoke(app, ["knowledge", "readiness", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)

    assert payload["readiness"]["status"] == "unsupported"
    assert payload["readiness"]["writes_settled"] is None
    assert payload["readiness"]["indexing_settled"] is None
    assert payload["gate"]["blocked"] is True
    assert payload["gate"]["evidence_grade"] == "not_run"
    assert "readback" in (payload["readiness"]["note"] or "")


def test_plan_rejects_a_non_memory_experiment(project: Path) -> None:
    target = project / "configs" / "experiments" / "knowledge-replay.yaml"
    target.write_text(
        (
            "schema_version: \"1.0\"\n"
            "id: not-memory\n"
            "version: \"1.0.0\"\n"
            "experiment:\n"
            "  type: configuration\n"
            "  agent:\n"
            "    id: codex\n"
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["knowledge", "plan"])

    assert result.exit_code == 1
    assert "no knowledge_replay experiment" in result.output

def test_plan_rejects_a_missing_file(project: Path) -> None:
    result = runner.invoke(app, ["knowledge", "plan", "/nonexistent/experiment.yaml"])
    assert result.exit_code == 1
