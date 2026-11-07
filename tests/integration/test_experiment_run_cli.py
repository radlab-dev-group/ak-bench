"""``akbench experiment run``: a whole matrix, executed and recorded.

The stub agent stands in for Codex, so the matrix, the orchestrator, the
evaluator and the history all run together. The point of these tests is the
whole point of the project: from one YAML file to runs recorded in the history
to a report, with nothing invented on the way.
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


def test_an_experiment_matrix_runs_and_reports_each_run(project: Path) -> None:
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert isinstance(payload, dict)
    # 1 task x 1 variant x 2 repetitions
    assert payload["planned"] == 2
    assert payload["completed"] == 2
    assert {run["state"] for run in payload["runs"]} == {"completed"}


def test_a_run_reports_when_it_started_and_how_long_it_took(project: Path) -> None:
    """A blocking run says where it started and what the clock read at the end."""
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--only", "1"])

    assert result.exit_code == 0, result.output
    assert "started " in result.output
    assert "took " in result.output


def test_the_json_result_carries_the_run_and_the_wall_clock(project: Path) -> None:
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--only", "1", "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert isinstance(payload, dict)
    assert payload["wall_seconds"] > 0
    run = payload["runs"][0]
    assert run["started_at"].endswith("+00:00")
    assert run["elapsed_seconds"] > 0


def test_runs_of_an_experiment_land_in_the_history_and_the_report(project: Path) -> None:
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"
    runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--json"])

    experiments = _json(runner.invoke(app, ["history", "experiments", "--json"]).output)
    row = next(item for item in experiments if item["uid"] == "wordcount-direct-sanity@1.0.0")
    assert row["runs"] == 2
    assert row["descriptor"] == "wordcount-direct-sanity@1.0.0"

    report = runner.invoke(app, ["report", "all", "--json"])
    assert report.exit_code == 0, report.output
    payload = _json(report.output)
    index = Path(payload["output"]) / "index.html"
    assert index.is_file()
    assert "wordcount-direct-sanity@1.0.0" in index.read_text(encoding="utf-8")


def test_only_limits_the_matrix_without_losing_the_plan(project: Path) -> None:
    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"

    result = runner.invoke(
        app, ["experiment", "run", str(experiment), "--store", "--only", "1", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert payload["completed"] == 1
    assert payload["planned"] == 2

    runs = _json(runner.invoke(app, ["history", "runs", "--json"]).output)
    assert len(runs) == 1
    assert runs[0]["repetition"] == 1


def test_an_unrunnable_experiment_is_refored_before_any_run(project: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text(
        """
schema_version: "1.0"
id: broken
version: "1.0.0"
title: A broken experiment
experiment:
  type: configuration
  agent: {id: ghost, version: "1.0.0"}
  execution: {mode: direct}
  dataset: {filters: {task_ids: [wordcount-001]}}
  factors: {strategy: full_factorial}
  execution_policy: {repetitions: 1}
  evaluation: {evaluators: [pytest_evaluator]}
  metrics: [task_success_rate]
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "run", str(broken)])

    assert result.exit_code == 1
    assert "not runnable" in result.output


def test_an_experiment_with_insufficient_timeout_is_refused(project: Path, tmp_path: Path) -> None:
    broken = tmp_path / "low_timeout.yaml"
    broken.write_text(
        """
schema_version: "1.0"
id: low-timeout
version: "1.0.0"
title: An experiment with timeout smaller than task
experiment:
  type: configuration
  agent: {id: codex, version: "1.0.0"}
  execution: {mode: direct}
  dataset: {filters: {task_ids: [wordcount-001]}}
  factors: {strategy: full_factorial}
  execution_policy: {repetitions: 1, timeout_seconds: 10}
  evaluation: {evaluators: [pytest_evaluator]}
  metrics: [task_success_rate]
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "run", str(broken)])

    assert result.exit_code == 1
    assert "not runnable" in result.output or "task_timeout_exceeds_experiment" in result.output


GATED_RUNTIME = """\
schema_version: "1.0"
id: gated-router
version: "1.0.0"
title: A router that names a credential
runtime:
  adapter: llm_router
  execution_modes: [router]
  supported_lifecycles: [external]
  base_url: http://127.0.0.1:1
  required_env: [AKBENCH_TEST_CREDENTIAL]
"""

ROUTER_EXPERIMENT = """\
schema_version: "1.0"
id: gated-run
version: "1.0.0"
title: A run whose runtime credential is missing
experiment:
  type: configuration
  agent: {id: codex, version: "1.0.0", config: {model: model-a}}
  execution: {mode: router, runtime: {id: gated-router}}
  dataset: {filters: {task_ids: [wordcount-001]}}
  factors: {strategy: full_factorial}
  execution_policy: {repetitions: 1, timeout_seconds: 600}
  evaluation: {evaluators: [pytest_evaluator]}
  metrics: [task_success_rate]
"""


def test_a_failed_run_reports_why_and_not_only_its_state(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal state without its reason is not a diagnosis.

    The runtime here names a credential nobody exports, so the agent refuses to
    start; the run must say so rather than print a bare state and send the user
    to a record file.
    """
    monkeypatch.delenv("AKBENCH_TEST_CREDENTIAL", raising=False)
    (project / "descriptors" / "runtimes" / "gated-router.yaml").write_text(
        GATED_RUNTIME, encoding="utf-8"
    )
    experiment = project / "gated-run.yaml"
    experiment.write_text(ROUTER_EXPERIMENT, encoding="utf-8")

    result = runner.invoke(app, ["experiment", "run", str(experiment)])

    assert result.exit_code == 0, result.output
    assert "invalid_configuration" in result.output
    assert "AKBENCH_TEST_CREDENTIAL" in result.output


def test_a_failed_run_carries_its_reason_into_the_json_result(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AKBENCH_TEST_CREDENTIAL", raising=False)
    (project / "descriptors" / "runtimes" / "gated-router.yaml").write_text(
        GATED_RUNTIME, encoding="utf-8"
    )
    experiment = project / "gated-run.yaml"
    experiment.write_text(ROUTER_EXPERIMENT, encoding="utf-8")

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert isinstance(payload, dict)
    run = payload["runs"][0]
    assert run["state"] == "invalid_configuration"
    assert "AKBENCH_TEST_CREDENTIAL" in str(run["detail"])


def test_a_run_is_visible_in_the_history_while_it_is_running(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-flight strip of the dashboard reads the history, so a run must be
    recorded when it starts, not only when it ends.

    The orchestrator is intercepted at its first transition, which is the run
    really in flight: the history must already hold its row in a non-terminal
    state, which is what the dashboard lists as active. When the run ends, the
    record of the end updates the same row instead of forking a second one.
    """
    from sqlalchemy import select

    from akbench.cli import experiments as experiment_cli
    from akbench.config.loader import load_settings, resolve_database_url
    from akbench.orchestration.lifecycle import TERMINAL_STATES, RunState
    from akbench.storage.db import create_db_engine, session_scope
    from akbench.storage.history import HistoryStore
    from akbench.storage.models import TaskRun

    def history(project_root: Path) -> HistoryStore:
        return HistoryStore(
            create_db_engine(resolve_database_url(load_settings(project_root=project_root).settings))
        )

    real_run = experiment_cli.RunOrchestrator.run
    seen: list[dict] = []

    def watch(self, config):
        # The first transition is the first state after the announcement; the
        # row the CLI wrote when the run started must be readable right now.
        config.on_transition(RunState.EXECUTING.value)
        store = history(project)
        row = store.run(config.run_uid)
        assert row is not None, "the run is not in the history while it runs"
        assert row["status"] not in TERMINAL_STATES
        seen.append(dict(row))
        return real_run(self, config)

    monkeypatch.setattr(experiment_cli.RunOrchestrator, "run", watch)

    experiment = EXPERIMENTS / "wordcount-direct-sanity.yaml"
    result = runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--only", "1"])

    assert result.exit_code == 0, result.output
    assert len(seen) == 1
    assert seen[0]["status"] == "executing"

    with session_scope(history(project).engine) as session:
        rows = session.scalars(select(TaskRun)).all()
    assert len(rows) == 1
    assert rows[0].status in TERMINAL_STATES
    assert history(project).runs()[0]["uid"] == seen[0]["uid"]
