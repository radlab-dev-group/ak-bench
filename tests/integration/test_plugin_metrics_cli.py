"""CLI behaviour of ``akbench plugin`` and ``akbench metrics``.

The commands read the descriptors shipped with the repository, so these tests
also guard the shipped plugin and metric definitions. The assertions here are
the honesty rules in action: a secret never reaches stdout, an unverifiable
plugin is reported as such, and an unmeasured metric stays unavailable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "ak-bench"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
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


def _record(tmp_path: Path, name: str, **overrides: object) -> Path:
    base: dict[str, object] = {
        "run_uid": f"run-{name}",
        "agent_id": "codex",
        "agent_version": "0.9.0",
        "state": "completed",
        "session_id": f"thread-{name}",
        "started_at": "2026-10-31T09:00:00+00:00",
        "finished_at": "2026-10-31T09:01:00+00:00",
        "observations": {
            "token_usage": {"input_tokens": 3000, "total_tokens": 4000},
            "tool_names": {"exec_command": 6},
        },
        "evaluation": {"verdict": "passed", "passed": 8, "failed": 0, "total": 8},
    }
    base.update(overrides)
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


# -------------------------------------------------------------------- plugin


def test_plugin_list_shows_the_shipped_plugins(project: Path) -> None:
    result = runner.invoke(app, ["plugin", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert {item["id"] for item in payload} == {"agentic_knowledge", "agentic_routing_codex"}
    knowledge = next(item for item in payload if item["id"] == "agentic_knowledge")
    assert knowledge["observed_env"] == 18
    assert knowledge["dimensions"]
    assert knowledge["verification_required"] is True


def test_plugin_status_never_prints_a_secret_value(project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "plugin",
            "status",
            "agentic_knowledge",
            "--env",
            "LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_TOKEN=hunter2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "hunter2" not in result.output
    payload = _payload(result.output)
    token = next(item for item in payload[0]["values"] if item["name"].endswith("SSE_API_TOKEN"))
    assert token["is_set"] is True
    assert token["observed"] is None
    assert token["sensitive"] is True


def test_plugin_status_reports_the_toggle_and_unavailable_metrics(project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "plugin",
            "status",
            "agentic_knowledge",
            "--env",
            "LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED=true",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload[0]["enabled"] is True
    assert payload[0]["state"]["verification_status"] == "unsupported"
    assert all(metric["available"] is False for metric in payload[0]["metrics"])
    assert all(metric["reason"] for metric in payload[0]["metrics"])


def test_plugin_verify_is_honest_without_evidence(project: Path) -> None:
    result = runner.invoke(app, ["plugin", "verify", "agentic_knowledge", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload[0]["verification_status"] == "unsupported"
    assert payload[0]["evidence"] is None
    assert payload[0]["methods_declared"]


def test_plugin_verify_checks_a_host_side_configuration_file(
    project: Path, tmp_path: Path
) -> None:
    config = tmp_path / "effective.json"
    config.write_text('{"LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED": true}', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "plugin",
            "verify",
            "agentic_knowledge",
            "--config-file",
            str(config),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload[0]["verification_status"] == "verified"
    assert payload[0]["evidence"] == "effective configuration file"


def test_plugin_status_rejects_an_unknown_plugin(project: Path) -> None:
    result = runner.invoke(app, ["plugin", "status", "ghost_plugin"])
    assert result.exit_code == 1
    assert "unknown plugin" in result.output


# ------------------------------------------------------------------- metrics


def test_metrics_catalog_lists_availability(project: Path) -> None:
    result = runner.invoke(app, ["metrics", "catalog", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert "task_success_rate" in payload
    assert payload["total_cost"]["availability"] == "unavailable"
    assert payload["total_cost"]["unavailable_reason"]
    assert payload["task_success_rate"]["availability"] == "computed"


def test_metrics_catalog_filters_by_group(project: Path) -> None:
    result = runner.invoke(app, ["metrics", "catalog", "--group", "quality", "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert set(payload) == {
        "task_success_rate",
        "hidden_test_pass_rate",
        "partial_success_rate",
        "regression_rate",
        "evaluator_score",
    }


def test_metrics_run_aggregates_and_deltas(project: Path, tmp_path: Path) -> None:
    baseline = _record(tmp_path, "base")
    variant = _record(
        tmp_path,
        "variant",
        finished_at="2026-10-31T09:00:20+00:00",
        observations={
            "token_usage": {"input_tokens": 900, "total_tokens": 1200},
            "tool_names": {"exec_command": 3},
        },
        evaluation={"verdict": "partial", "passed": 6, "failed": 2, "total": 8},
    )
    result = runner.invoke(
        app,
        [
            "metrics",
            "run",
            str(variant),
            "--baseline",
            str(baseline),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["runs"] == 1
    metrics = payload["metrics"]
    assert metrics["task_success_rate"]["mean"] == 0.0
    assert metrics["knowledge_write_count"]["measured"] == 0
    assert metrics["knowledge_write_count"]["reasons"]

    deltas = {item["metric"]: item for item in payload["deltas"]}
    assert deltas["task_success_rate"]["value"] == pytest.approx(-1.0)
    assert deltas["execution_time"]["value"] == pytest.approx(3.0)
    assert deltas["total_tokens"]["value"] == pytest.approx(0.7)
    assert payload["interpretation"]


def test_metrics_run_requires_a_record(project: Path) -> None:
    result = runner.invoke(app, ["metrics", "run"])
    assert result.exit_code == 1
    assert "no run record" in result.output


def test_metrics_run_rejects_a_missing_file(project: Path) -> None:
    result = runner.invoke(app, ["metrics", "run", "/nonexistent/run_record.json"])
    assert result.exit_code == 1
    assert "not found" in result.output
