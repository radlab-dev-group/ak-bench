"""The scheduler-facing commands: concurrency, resume, cancel.

``akbench experiment run`` is the scheduler — there is no daemon — so these
tests drive what the CLI actually does: a matrix run at a concurrency greater
than one keeps its results in plan order, a resume fills the cells the history
has no verdict for and never duplicates a cell, and a cancel that arrives from
another process stops the run in flight and records it cancelled with its
artifacts kept.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB = REPO_ROOT / "tests" / "contract" / "stubs" / "codex_fixer_stub.py"
EXPERIMENTS = REPO_ROOT / "configs" / "experiments"
runner = CliRunner()

#: A stub that starts and never finishes, so a cancel has something to stop.
HANG_STUB = '''#!/usr/bin/env python3
"""A fake agent that prints a version and then waits to be interrupted."""
import signal
import sys
import time

if "--version" in sys.argv:
    print("codex-cli 0.0.0-hang")
    sys.exit(0)

def _stop(_signum, _frame):
    sys.exit(130)

signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)
while True:
    time.sleep(0.1)
'''


def _project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, hang: bool) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "ak-bench"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    shutil.copytree(REPO_ROOT / "datasets", root / "datasets")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
    (root / "bin").mkdir()
    stub = root / "bin" / "codex"
    if hang:
        stub.write_text(HANG_STUB, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | 0o111)
    else:
        shutil.copyfile(STUB, stub)
        stub.chmod(stub.stat().st_mode | 0o111)
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    monkeypatch.setenv("PATH", os.pathsep.join([str(root / "bin"), os.environ["PATH"]]))
    for name in list(os.environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    return _project(monkeypatch, tmp_path, hang=False)


def _json(output: str) -> dict:
    decoder = json.JSONDecoder()
    starts = [index for index in (output.find("["), output.find("{")) if index != -1]
    assert starts, f"no JSON in output: {output[:300]!r}"
    payload, _ = decoder.raw_decode(output[min(starts) :])
    return payload


def _experiment(root: Path, *, repetitions: int, concurrency: int) -> Path:
    """The shipped sanity experiment with its policy rewritten."""
    text = (EXPERIMENTS / "wordcount-direct-sanity.yaml").read_text(encoding="utf-8")
    text = text.replace("repetitions: 2", f"repetitions: {repetitions}")
    text = text.replace("concurrency: 1", f"concurrency: {concurrency}")
    path = root / "concurrent.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_concurrency_runs_every_cell_and_keeps_the_plan_order(project: Path) -> None:
    """Four cells at concurrency two: all run, and the report reads in plan order.

    The order is the point, not an accident of the schedule: a reader
    comparing this report with the plan must not have to reconstruct which
    repetition finished first.
    """
    experiment = _experiment(project, repetitions=4, concurrency=2)

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--json"])

    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert payload["planned"] == 4
    assert payload["completed"] == 4
    assert [run["repetition"] for run in payload["runs"]] == [1, 2, 3, 4]
    assert {run["state"] for run in payload["runs"]} == {"completed"}


def test_the_concurrency_of_a_run_comes_from_its_policy(project: Path) -> None:
    """The plan reports the concurrency it will use, so an override is visible."""
    experiment = _experiment(project, repetitions=2, concurrency=3)

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--concurrency", "2"])

    assert result.exit_code == 0, result.output
    assert "concurrency 2" in result.output


def test_resume_runs_the_cells_that_have_no_verdict_and_dup_nothing(project: Path) -> None:
    """A resume fills the gaps; a second resume of the same experiment is a no-op.

    The key is the matrix cell (task, variant, repetition) in the history, so
    resuming twice cannot produce two runs of a cell that already has one.
    """
    experiment = _experiment(project, repetitions=3, concurrency=1)

    first = runner.invoke(
        app, ["experiment", "run", str(experiment), "--store", "--json", "--only", "1"]
    )
    assert first.exit_code == 0, first.output
    assert _json(first.output)["completed"] == 1
    uid = _json(first.output)["experiment"]

    resumed = runner.invoke(app, ["experiment", "resume", uid, "--json"])
    assert resumed.exit_code == 0, resumed.output
    payload = _json(resumed.output)
    assert payload["completed"] == 2, "the two cells without a verdict are run"
    assert payload.get("already_done") == 1

    again = runner.invoke(app, ["experiment", "resume", uid, "--json"])
    assert again.exit_code == 0, again.output
    assert _json(again.output)["completed"] == 0, "a finished experiment resumes to nothing"


def test_resume_reruns_what_was_cancelled(project: Path) -> None:
    """A cancelled cell is an operator's decision, not a result — it runs again."""
    uid = "wordcount-direct-sanity@1.0.0"
    from akbench.cli.common import CliContext
    from akbench.config.loader import resolve_database_url
    from akbench.storage.db import create_db_engine
    from akbench.storage.history import HistoryStore

    experiment = _experiment(project, repetitions=1, concurrency=1)
    run = runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--json"])
    assert run.exit_code == 0, run.output
    uid = _json(run.output)["experiment"]

    context = CliContext()
    store = HistoryStore(create_db_engine(resolve_database_url(context.loaded().settings)))
    row = store.runs(uid)[0]
    # Record a cancelled cell the way a cancelled run left it, then resume.
    _mark_cancelled(store, row["uid"])

    resumed = runner.invoke(app, ["experiment", "resume", uid, "--json"])
    assert resumed.exit_code == 0, resumed.output
    assert _json(resumed.output)["completed"] == 1, "a cancelled cell is re-run"


def _mark_cancelled(store, run_uid: str) -> None:
    from sqlalchemy import select

    from akbench.storage.db import session_scope
    from akbench.storage.models import TaskRun

    with session_scope(store.engine) as session:
        row = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
        row.status = "cancelled"


def test_cancel_stops_a_run_in_flight_and_keeps_its_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``experiment cancel`` from another process ends the matrix within seconds.

    This is the whole of what a one-shot CLI can honestly offer: a marker the
    running process watches, the agent in flight interrupted, the run recorded
    cancelled with its artifacts, and no further cell started.
    """
    root = _project(monkeypatch, tmp_path, hang=True)
    experiment = _experiment(root, repetitions=4, concurrency=1)
    environment = dict(os.environ)
    environment["AKBENCH_HOME"] = str(root)
    environment["PATH"] = os.pathsep.join([str(root / "bin"), environment["PATH"]])

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "akbench.cli.main",
            "experiment",
            "run",
            str(experiment),
            "--store",
            "--json",
        ],
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    uid = "wordcount-direct-sanity@1.0.0"
    marker = root / "data" / "cancellations" / f"{uid}.cancel"

    # Give the first run a moment to reach the agent, then ask from the side.
    deadline = time.time() + 30
    while time.time() < deadline and not _agent_is_running(root):
        time.sleep(0.2)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("cancelled by the test\n", encoding="utf-8")

    try:
        output = process.communicate(timeout=90)[0]
    except subprocess.TimeoutExpired:  # pragma: no cover - a hang is the failure
        process.kill()
        pytest.fail("the run did not stop after the cancel marker")

    assert "cancelled" in output.lower(), output[-800:]
    from akbench.cli.common import CliContext
    from akbench.config.loader import resolve_database_url
    from akbench.storage.db import create_db_engine
    from akbench.storage.history import HistoryStore

    context = CliContext(project_root=root)
    store = HistoryStore(create_db_engine(resolve_database_url(context.loaded().settings)))
    runs = store.runs(uid)
    assert runs, "the cancelled run is recorded"
    assert runs[0]["status"] == "cancelled"
    assert len(runs) < 4, "the matrix stopped; the remaining cells were never started"
    record = next((root / "data" / "artifacts").rglob("run_record.json"))
    assert record.is_file(), "the run keeps its artifacts"


def _agent_is_running(root: Path) -> bool:
    """True once the first run has reached the point with something to cancel."""
    from akbench.cli.common import CliContext
    from akbench.config.loader import resolve_database_url
    from akbench.storage.db import create_db_engine
    from akbench.storage.history import HistoryStore

    try:
        context = CliContext(project_root=root)
        store = HistoryStore(create_db_engine(resolve_database_url(context.loaded().settings)))
        if store.runs("wordcount-direct-sanity@1.0.0"):
            return True
    except Exception:
        pass
    return any((root / "data" / "workspaces").rglob("*")) if (root / "data").exists() else False


def test_a_run_of_a_declared_environment_records_it_in_the_manifest(project: Path) -> None:
    """A run that declared an environment says so in its manifest, next to sandbox_image.

    The manifest is what a month later answers "where did this run happen";
    an experiment that named the environment has the run carry that name, its
    digest and its sandbox, and the host run states host rather than leaving
    the field to be read as whatever the reader assumes.
    """
    text = (EXPERIMENTS / "wordcount-direct-sanity.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "  execution_policy:",
        "  environment:\n    id: local-host\n\n  execution_policy:",
    )
    experiment = project / "env.yaml"
    experiment.write_text(text, encoding="utf-8")

    result = runner.invoke(app, ["experiment", "run", str(experiment), "--store", "--json"])

    assert result.exit_code == 0, result.output
    artifacts = project / "data" / "artifacts"
    record = json.loads(next(artifacts.rglob("run_record.json")).read_text(encoding="utf-8"))
    manifest = json.loads(next(artifacts.rglob("manifest.json")).read_text(encoding="utf-8"))

    payload = _json(result.output)
    assert payload["completed"] == 2
    assert record["environment"]["id"] == "local-host"
    assert record["environment"]["sandbox"] == "host"
    assert record["environment"]["digest"].startswith("sha256:")
    assert manifest["environment"]["id"] == "local-host"
    assert manifest["environment"]["digest"].startswith("sha256:")
    # A host run has no image; the manifest states the environment instead of
    # inventing a sandbox_image it did not have.
    assert manifest["sandbox_image"] is None
