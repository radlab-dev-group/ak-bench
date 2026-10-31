"""CLI behaviour of ``akbench experiment``: list, validate and plan.

The commands work on the experiment files shipped with the repository, so the
tests double as a guard on those examples: a shipped experiment that stops
planning is a broken promise, not a test failure to debug later.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
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
    shutil.copytree(EXPERIMENTS, root / "configs" / "experiments")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(__import__("os").environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _payload(output: str) -> dict | list:
    """Parse the JSON document a command printed, ignoring any log prefix."""
    decoder = json.JSONDecoder()
    starts = [index for index in (output.find("["), output.find("{")) if index != -1]
    assert starts, f"no JSON in output: {output[:200]!r}"
    payload, _ = decoder.raw_decode(output[min(starts) :])
    return payload


def test_list_shows_the_shipped_experiments(project: Path) -> None:
    result = runner.invoke(app, ["experiment", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    for name in ("full-matrix", "knowledge-on-off", "model-comparison"):
        assert name in {item["id"] for item in payload}


def test_list_json_is_machine_readable(project: Path) -> None:
    result = runner.invoke(app, ["experiment", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert isinstance(payload, list)
    assert {item["id"] for item in payload} == {
        "full-matrix",
        "knowledge-on-off",
        "knowledge-replay",
        "model-comparison",
        "wordcount-direct-sanity",
    }


def test_validate_accepts_the_shipped_experiments(project: Path) -> None:
    result = runner.invoke(app, ["experiment", "validate"])

    assert result.exit_code == 0, result.output
    assert result.output.count("ok ") >= 5
    assert "invalid" not in result.output


def test_validate_json_carries_the_findings(project: Path) -> None:
    result = runner.invoke(app, ["experiment", "validate", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert len(payload) == 5
    for item in payload:
        assert item["validation"]["ok"] is True


def test_validate_reports_a_broken_experiment(project: Path) -> None:
    broken = project / "broken.yaml"
    broken.write_text(
        """
schema_version: "1.0"
id: broken
version: "1.0.0"
experiment:
  agent:
    id: no-such-agent
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "validate", str(broken)])

    assert result.exit_code == 1
    assert "invalid" in result.output
    assert "no-such-agent" in result.output


def test_plan_prints_the_size_of_the_experiment(project: Path) -> None:
    result = runner.invoke(
        app, ["experiment", "plan", str(project / "configs" / "experiments" / "full-matrix.yaml")]
    )

    assert result.exit_code == 0, result.output
    assert "6 variants" in result.output
    assert "18 runs" in result.output
    assert "wordcount-001@1.0.0" in result.output


def test_plan_json_contains_variants_and_validation(project: Path) -> None:
    target = project / "configs" / "experiments" / "knowledge-on-off.yaml"
    result = runner.invoke(app, ["experiment", "plan", str(target), "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["counts"] == {"tasks": 1, "variants": 2, "repetitions": 3, "runs": 6}
    assert {variant["is_baseline"] for variant in payload["variants"]} == {True, False}
    assert all(value.startswith("sha256:") for value in payload["descriptor_snapshots"].values())
    assert payload["validation"]["ok"] is True


def test_plan_refuses_an_unrunnable_experiment(project: Path) -> None:
    broken = project / "broken.yaml"
    broken.write_text(
        """
schema_version: "1.0"
id: broken
version: "1.0.0"
experiment:
  agent:
    id: no-such-agent
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "plan", str(broken)])

    assert result.exit_code == 1
    assert "not runnable" in result.output
    assert "no-such-agent" in result.output


def test_plan_rejects_a_missing_file(project: Path) -> None:
    result = runner.invoke(app, ["experiment", "plan", str(project / "nope.yaml")])

    assert result.exit_code == 1
    assert "not found" in result.output
