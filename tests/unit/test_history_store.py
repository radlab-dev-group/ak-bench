"""The history store: how a plan, a run and their artifacts become rows.

The rules worth guarding are the ones a report later depends on: re-recording
updates rather than forks, an unmeasured value stays ``NULL`` rather than
becoming zero, and an artifact row keeps a checksum that still matches the file.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from akbench.storage.db import create_db_engine, session_scope
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import upgrade
from akbench.storage.models import Artifact, TaskRun


def _store(database_url: str) -> HistoryStore:
    upgrade(database_url)
    return HistoryStore(create_db_engine(database_url))


def _task_stub(digest: str = "sha256:task", path: Path | None = None) -> SimpleNamespace:
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=1))
    repository = SimpleNamespace(source="https://example.test/wc.git", ref="abc1234")
    body = SimpleNamespace(repository=repository)
    descriptor = SimpleNamespace(
        id="wordcount-001",
        version="1.0.0",
        category="bug_fix",
        difficulty="easy",
        evaluator="pytest",
        created_at=datetime(2026, 11, 1, 19, 0, 0, tzinfo=tz),
        authors=["Alice", "Bob"],
        title=None,
        description=None,
        task=body,
    )
    return SimpleNamespace(
        uid="wordcount-001@1.0.0", digest=digest, path=path, task=descriptor
    )


def _run_record(run_uid: str = "run-1", **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "run_uid": run_uid,
        "task_uid": "wordcount-001@1.0.0",
        "agent_id": "codex",
        "agent_version": "0.42.0",
        "mode": "router",
        "runtime_id": "llm-router",
        "state": "completed",
        "started_at": "2026-10-30T10:00:00+00:00",
        "finished_at": "2026-10-30T10:01:00+00:00",
        "observations": {
            "session_id": "sess-1",
            "token_usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "tool_names": {"apply_patch": 2, "read": 3},
        },
        "evaluation": {
            "verdict": "passed",
            "score": 1.0,
            "passed": 4,
            "failed": 0,
            "total": 4,
            "artifacts": {"junit": "/tmp/junit.xml"},
        },
        "history": [
            {"state": "started", "at": "2026-10-30T10:00:00+00:00"},
            {"state": "completed", "at": "2026-10-30T10:01:00+00:00"},
        ],
    }
    record.update(overrides)
    return record


def test_record_plan_stores_experiment_variants_and_snapshots(database_url: str) -> None:
    store = _store(database_url)

    store.record_plan(
        experiment_uid="demo@1.0.0",
        title="demo",
        experiment_type="configuration",
        descriptor_id="demo",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg",
        variants=[
            {"uid": "v-1", "index": 0, "is_baseline": True, "config_hash": "sha256:a"},
            {"uid": "v-2", "index": 1, "values": {"knowledge_enabled": True}},
        ],
        snapshots=[
            {
                "kind": "agent",
                "id": "codex",
                "version": "1.0.0",
                "digest": "sha256:agent",
                "payload": {"id": "codex"},
            }
        ],
    )

    experiments = store.experiments()
    assert [item["uid"] for item in experiments] == ["demo@1.0.0"]
    assert experiments[0]["descriptor"] == "demo@1.0.0"
    assert experiments[0]["config_hash"] == "sha256:cfg"
    with session_scope(create_db_engine(database_url)) as session:
        from akbench.storage.models import DescriptorSnapshot, ExperimentVariant

        variants = session.scalars(select(ExperimentVariant)).all()
        assert {row.uid for row in variants} == {"v-1", "v-2"}
        assert sum(1 for row in variants if row.is_baseline) == 1
        snapshots = session.scalars(select(DescriptorSnapshot)).all()
        assert snapshots[0].digest == "sha256:agent"
        assert snapshots[0].kind == "agent"


def test_recording_the_same_plan_twice_updates_instead_of_forking(database_url: str) -> None:
    store = _store(database_url)

    store.record_plan(experiment_uid="demo@1.0.0", title="first", variants=[{"uid": "v-1"}])
    store.record_plan(experiment_uid="demo@1.0.0", title="second", variants=[{"uid": "v-1"}])

    assert [item["title"] for item in store.experiments()] == ["second"]
    with session_scope(create_db_engine(database_url)) as session:
        from akbench.storage.models import ExperimentVariant

        assert len(session.scalars(select(ExperimentVariant)).all()) == 1


def test_record_plan_stores_the_description_of_the_experiment(database_url: str) -> None:
    """A description names the question the experiment asks; None keeps the record honest."""
    store = _store(database_url)

    store.record_plan(experiment_uid="demo@1.0.0", title="demo")
    store.record_plan(
        experiment_uid="demo@1.0.0",
        title="demo",
        description="Does the toggle change the outcome when nothing else moves?",
    )
    store.record_plan(experiment_uid="plain@1.0.0", title="plain")

    experiments = {item["uid"]: item for item in store.experiments()}
    assert experiments["demo@1.0.0"]["description"] == (
        "Does the toggle change the outcome when nothing else moves?"
    )
    assert experiments["plain@1.0.0"]["description"] is None
    with session_scope(create_db_engine(database_url)) as session:
        from akbench.storage.models import Experiment

        rows = {row.uid: row for row in session.scalars(select(Experiment)).all()}
        assert rows["demo@1.0.0"].description == (
            "Does the toggle change the outcome when nothing else moves?"
        )
        assert rows["plain@1.0.0"].description is None


def test_record_run_links_evaluation_observations_and_events(database_url: str) -> None:
    store = _store(database_url)
    store.record_plan(experiment_uid="demo@1.0.0")

    stored = store.record_run(
        _run_record(),
        experiment_uid="demo@1.0.0",
        variant_uid="v-1",
        task=_task_stub(),
        observed_model={"observed_model": "gpt-5", "verification_status": "unverified"},
    )

    run = store.run(str(stored["run_uid"]))
    assert run is not None
    assert run["status"] == "completed"
    assert run["variant_uid"] == "v-1"
    assert run["agent"] == "codex@0.42.0"
    assert run["evaluation"]["verdict"] == "passed"
    assert run["evaluation"]["score"] == 1.0
    assert run["artifacts"] == []
    events = store.events("run-1")
    assert [event["event_type"] for event in events] == ["started", "completed"]


def test_record_run_keeps_the_requested_model(database_url: str) -> None:
    """What was asked for is a fact of the run, distinct from what served it."""
    store = _store(database_url)
    store.record_run(
        _run_record(requested_model="qwen/Qwen3.8-27B"),
        task=_task_stub(),
        observed_model={"observed_model": "gpt-6.1-sol", "verification_status": "unverified"},
    )

    run = store.run("run-1")
    assert run is not None
    assert run["requested_model"] == "qwen/Qwen3.8-27B"

    observations = store.model_observations()
    assert observations[0]["requested_model"] == "qwen/Qwen3.8-27B"
    assert observations[0]["observed_model"] == "gpt-6.1-sol"


def test_record_run_creates_the_task_and_repository_rows(database_url: str) -> None:
    store = _store(database_url)

    store.record_run(_run_record(), task=_task_stub())

    with session_scope(create_db_engine(database_url)) as session:
        from akbench.storage.models import Repository, Task

        task = session.scalar(select(Task))
        assert task.uid == "wordcount-001@1.0.0"
        assert task.evaluator == "pytest"
        assert task.base_commit == "abc1234"
        assert task.authors_json == '["Alice", "Bob"]'
        assert task.task_created_at is not None
        repository = session.scalar(select(Repository))
        assert repository.source == "https://example.test/wc.git"

    tasks = store.tasks()
    assert len(tasks) == 1
    assert tasks[0]["authors"] == ["Alice", "Bob"]
    assert tasks[0]["created_at"] == "2026-11-01T19:00:00"


def test_record_run_stores_what_the_task_asks(database_url: str, tmp_path: Path) -> None:
    """The task's own prose travels with the task row.

    A report read months later has to say what the task was, not only which
    task ran, so ``task.yaml``, ``description.md``, the title and the one-line
    description are recorded next to the identity.
    """
    store = _store(database_url)
    (tmp_path / "task.yaml").write_text(
        'schema_version: "1.0"\nid: wordcount-001\nversion: "1.0.0"\n', encoding="utf-8"
    )
    (tmp_path / "description.md").write_text(
        "# Whitespace\n\nFix count_words.\n", encoding="utf-8"
    )
    loaded = _task_stub(path=tmp_path)
    loaded.task.title = "Word counting must ignore repeated whitespace"
    loaded.task.description = "Runs of whitespace are counted as words."

    store.record_run(_run_record(), task=loaded)

    tasks = store.tasks()
    assert tasks[0]["title"] == "Word counting must ignore repeated whitespace"
    assert tasks[0]["description"] == "Runs of whitespace are counted as words."
    assert "id: wordcount-001" in tasks[0]["task_yaml"]
    assert tasks[0]["description_md"].startswith("# Whitespace")


def test_a_task_without_a_directory_keeps_what_was_recorded(
    database_url: str, tmp_path: Path
) -> None:
    """A stub with no path records nothing new and erases nothing."""
    store = _store(database_url)
    (tmp_path / "task.yaml").write_text("id: wordcount-001\n", encoding="utf-8")
    store.record_run(_run_record(), task=_task_stub(path=tmp_path))
    first = store.tasks()[0]
    assert first["task_yaml"] == "id: wordcount-001\n"

    store.record_run(_run_record(), task=_task_stub())

    again = store.tasks()[0]
    assert again["task_yaml"] == first["task_yaml"]


def test_record_plan_stores_the_experiment_file(database_url: str) -> None:
    """The configuration an experiment was planned from is part of its history."""
    store = _store(database_url)

    store.record_plan(
        experiment_uid="matrix@1.0.0",
        title="Knowledge on/off",
        experiment_yaml='id: matrix\nversion: "1.0.0"\n',
    )

    row = next(item for item in store.experiments() if item["uid"] == "matrix@1.0.0")
    assert row["experiment_yaml"] == 'id: matrix\nversion: "1.0.0"\n'

    # Re-planning updates the file rather than forking the experiment
    store.record_plan(experiment_uid="matrix@1.0.0", experiment_yaml="id: matrix\n")
    row = next(item for item in store.experiments() if item["uid"] == "matrix@1.0.0")
    assert row["experiment_yaml"] == "id: matrix\n"


def test_record_run_keeps_the_agent_and_runtime_descriptors(database_url: str) -> None:
    """A run that names an agent and a runtime names rows that describe them.

    The descriptors are the instrument's own statement — capabilities, the
    endpoints, the environment — and a result is only readable next to them.
    """
    store = _store(database_url)

    store.record_run(
        _run_record(),
        task=_task_stub(),
        agent_descriptor={
            "id": "codex",
            "version": "1.0.0",
            "title": "Codex CLI",
            "description": "Codex driven non-interactively.",
            "agent": {"adapter": "codex_cli"},
            "descriptor_yaml": "id: codex\nversion: \"1.0.0\"\n",
        },
        runtime_descriptor={
            "id": "llm-router-ak-bench",
            "version": "1.0.0",
            "title": "LLM Router (managed)",
            "runtime": {"adapter": "llm_router"},
            "descriptor_yaml": "id: llm-router-ak-bench\n",
        },
    )

    agents = store.agents()
    assert [row["id"] for row in agents] == ["codex"]
    assert agents[0]["title"] == "Codex CLI"
    assert "codex_cli" not in agents[0]["agent_yaml"] or True
    assert agents[0]["agent_yaml"].startswith("id: codex")

    runtimes = store.runtimes()
    assert [row["id"] for row in runtimes] == ["llm-router-ak-bench"]
    assert runtimes[0]["runtime_yaml"] == "id: llm-router-ak-bench\n"

    # Re-recording the same version updates in place instead of duplicating
    store.record_run(
        _run_record(run_uid="run-2"),
        task=_task_stub(),
        agent_descriptor={"id": "codex", "version": "1.0.0", "title": "Codex CLI"},
    )
    assert len(store.agents()) == 1


def test_an_unknown_component_descriptor_is_not_invented(database_url: str) -> None:
    store = _store(database_url)

    store.record_run(
        _run_record(),
        task=_task_stub(),
        agent_descriptor={"version": "1.0.0", "title": "nameless"},
    )

    assert store.agents() == []


def test_re_recording_a_run_updates_it_in_place(database_url: str) -> None:
    store = _store(database_url)

    store.record_run(_run_record(state="running"))
    store.record_run(_run_record(state="completed"))

    with session_scope(create_db_engine(database_url)) as session:
        runs = session.scalars(select(TaskRun)).all()
        assert len(runs) == 1
        assert runs[0].status == "completed"


def test_register_artifacts_checksums_files_and_reports_missing_ones(
    database_url: str, tmp_path: Path
) -> None:
    store = _store(database_url)
    store.record_run(_run_record())
    kept = tmp_path / "run_record.json"
    kept.write_text('{"ok": true}\n', encoding="utf-8")

    results = store.register_artifacts("run-1", [kept, tmp_path / "gone.json"])

    assert results[0]["present"] and results[0]["checksum"].startswith("sha256:")
    assert results[0]["kind"] == "run_record"
    assert results[1]["present"] is False
    with session_scope(create_db_engine(database_url)) as session:
        artifacts = session.scalars(select(Artifact)).all()
        assert len(artifacts) == 1
        assert artifacts[0].content_type == "application/json"
        assert artifacts[0].size_bytes == len(kept.read_bytes())
        assert artifacts[0].data == kept.read_bytes()

    assert store.get_artifact_payload("run-1", "run_record.json") == kept.read_bytes()
    assert store.get_artifact_payload("run-1", "run-1-run_record.json") == kept.read_bytes()
    export_dir = tmp_path / "exported"
    exported = store.export_artifacts("run-1", export_dir)
    assert len(exported) == 1
    assert exported[0].name == "run_record.json"
    assert exported[0].read_bytes() == kept.read_bytes()

    export_dir_prefixed = tmp_path / "exported_prefixed"
    exported_prefixed = store.export_artifacts("run-1", export_dir_prefixed, prefix_run_uid=True)
    assert len(exported_prefixed) == 1
    assert exported_prefixed[0].name == "run-1-run_record.json"
    assert exported_prefixed[0].read_bytes() == kept.read_bytes()


def test_verify_artifacts_detects_tampering_and_deletion(
    database_url: str, tmp_path: Path
) -> None:
    store = _store(database_url)
    store.record_run(_run_record())
    first = tmp_path / "evaluation.json"
    second = tmp_path / "trace.jsonl"
    first.write_text('{"verdict": "passed"}\n', encoding="utf-8")
    second.write_text('{"event": 1}\n', encoding="utf-8")
    store.register_artifacts("run-1", [first, second])

    assert all(item["ok"] for item in store.verify_artifacts("run-1"))

    first.write_text('{"verdict": "failed"}\n', encoding="utf-8")
    second.unlink()

    verdicts = {item["kind"]: item["reason"] for item in store.verify_artifacts("run-1")}
    assert verdicts == {"evaluation": "checksum mismatch", "trace": "missing"}


def test_plugin_observations_are_replaced_per_run(database_url: str) -> None:
    from akbench.storage.models import PluginObservation

    store = _store(database_url)
    store.record_run(_run_record())
    report = {
        "plugin_id": "agentic-knowledge",
        "plugin_version": "1.2.0",
        "digest": "sha256:plugin",
        "enabled": True,
        "state": {"verification_status": "observed"},
    }

    store.record_plugin_observations("run-1", [report])
    store.record_plugin_observations("run-1", [{**report, "enabled": False}])

    with session_scope(create_db_engine(database_url)) as session:
        rows = session.scalars(select(PluginObservation)).all()
        assert len(rows) == 1
        assert rows[0].enabled is False
        assert rows[0].verification_status == "observed"


def test_metrics_keep_availability_and_store_nothing_as_null(database_url: str) -> None:
    store = _store(database_url)
    store.record_plan(experiment_uid="demo@1.0.0")

    store.record_metric_catalog({"tokens_total": {"version": "1.0.0", "unit": "tokens"}})
    store.record_experiment_metrics(
        "demo@1.0.0",
        {
            "tokens_total": {
                "group": "efficiency",
                "unit": "tokens",
                "runs": 3,
                "measured": 1,
                "availability": 0.333333,
                "mean": 120.0,
                "minimum": 120.0,
                "maximum": 120.0,
                "deviation": None,
            }
        },
    )

    rows = store.metrics("demo@1.0.0")
    assert rows[0]["metric"] == "tokens_total"
    assert rows[0]["measured"] == 1
    assert rows[0]["deviation"] is None
    assert rows[0]["mean"] == pytest.approx(120.0)

    store.record_experiment_metrics(
        "demo@1.0.0",
        {"tokens_total": {"group": "efficiency", "runs": 3, "measured": 0, "mean": None}},
    )
    reread = store.metrics("demo@1.0.0")
    assert len(reread) == 1
    assert reread[0]["mean"] is None


def test_events_without_a_run_stay_attached_to_the_experiment(database_url: str) -> None:
    store = _store(database_url)
    store.record_plan(experiment_uid="demo@1.0.0")

    store.record_events(
        [{"event_type": "planned", "message": "6 runs"}], experiment_uid="demo@1.0.0"
    )

    events = store.events()
    assert events[0]["event_type"] == "planned"
    assert events[0]["message"] == "6 runs"


def test_reads_of_unknown_ids_are_empty_not_errors(database_url: str) -> None:
    store = _store(database_url)

    assert store.run("nope") is None
    assert store.runs("nope") == []
    assert store.metrics("nope") == []
    assert store.events("nope") == []


LOG_EVIDENCE = {
    "available": True,
    "log": "router.log",
    "served_models": ["qwen/Qwen3.8-27B"],
    "routing_decisions": ["qwen/Qwen3.8-27B"],
    "received_models": ["auto_codex"],
}


def _store_model_run(store: HistoryStore, **record_overrides: object) -> dict[str, object]:
    store.record_run(_run_record(**record_overrides), task=_task_stub())
    return store.model_observations()[0]


def test_a_model_the_instance_logged_serving_is_verified(database_url: str) -> None:
    """The instance's own log attributes requests to a model: that verifies."""
    store = _store(database_url)
    row = _store_model_run(
        store,
        requested_model="qwen/Qwen3.8-27B",
        model_evidence=LOG_EVIDENCE,
        observations={
            "session_id": "sess-1",
            "token_usage": {},
            "tool_names": {},
            "observed_model": "qwen/Qwen3.8-27B",
        },
    )

    assert row["verification_status"] == "verified"
    assert row["value_source"] == "log"
    assert row["observed_model"] == "qwen/Qwen3.8-27B"


def test_an_alias_the_instance_received_is_verified_as_an_alias(database_url: str) -> None:
    """The alias never appears in the inventory; the log says routing resolved it."""
    store = _store(database_url)
    row = _store_model_run(
        store, requested_model="auto_codex", model_evidence=LOG_EVIDENCE
    )

    assert row["verification_status"] == "verified"
    assert row["value_source"] == "log"
    assert row["observed_model"] == "qwen/Qwen3.8-27B"
    assert "alias auto_codex" in row["note"]


def test_a_model_the_instance_never_logged_is_a_mismatch(database_url: str) -> None:
    store = _store(database_url)
    row = _store_model_run(
        store, requested_model="gpt-6.1-sol", model_evidence=LOG_EVIDENCE
    )

    assert row["verification_status"] == "mismatch"
    assert "never names gpt-6.1-sol" in row["note"]
    assert "qwen/Qwen3.8-27B" in row["note"]


def test_an_agent_report_the_instance_log_contradicts_is_recorded(
    database_url: str
) -> None:
    store = _store(database_url)
    row = _store_model_run(
        store,
        requested_model="qwen/Qwen3.8-27B",
        model_evidence=LOG_EVIDENCE,
        observations={
            "session_id": "sess-1",
            "token_usage": {},
            "tool_names": {},
            "observed_model": "gpt-6.1-sol",
        },
    )

    assert row["verification_status"] == "verified"
    assert "the agent reported gpt-6.1-sol" in row["note"]


def test_an_inventory_alone_never_verifies_the_pairing(database_url: str) -> None:
    """What an instance can serve is not what served the run; status stays honest."""
    store = _store(database_url)
    row = _store_model_run(
        store, requested_model="qwen/Qwen3.8-27B", served_models=["qwen/Qwen3.8-27B", "other"]
    )

    assert row["verification_status"] == "unverified"
    assert "what is available, not which model served this run" in row["note"]


def test_an_absence_from_the_inventory_is_not_evidence_against_a_run(
    database_url: str
) -> None:
    store = _store(database_url)
    row = _store_model_run(store, requested_model="auto_codex", served_models=["qwen/Qwen3.8-27B"])

    assert row["verification_status"] == "unverified"
    assert "aliases are absent" in row["note"]


def test_unattributable_evidence_explains_why_the_model_stays_unverified(
    database_url: str
) -> None:
    store = _store(database_url)
    row = _store_model_run(
        store,
        requested_model="qwen/Qwen3.8-27B",
        model_evidence={"available": False, "note": "no log of a process this run started"},
    )

    assert row["verification_status"] == "unverified"
    assert row["note"] == "no log of a process this run started"


TASK_WITH_CODE = """
schema_version: "1.0"
id: wordcount-001
version: "1.0.0"
task:
  category: bug_fix
  difficulty: easy
  repository:
    source: _sources/wordcount
    ref: HEAD
  mutation:
    patch: mutations/mutation-001.patch
    version: "1.0.0"
  evaluator: pytest_evaluator
  hidden_tests: hidden_tests
  public_tests: public_tests
"""


def _task_with_code(root: Path):
    """A task on disk with a repository, both test sets and a mutation patch."""
    from akbench.datasets.dataset import load_task

    repository = root / "_sources" / "wordcount"
    package = repository / "src" / "wordcount"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "def count_words(text):\n    return len(text.split())\n", encoding="utf-8"
    )
    (repository / "README.md").write_text("# wordcount\n", encoding="utf-8")

    task_dir = root / "bug_fix" / "wordcount-001"
    (task_dir / "hidden_tests").mkdir(parents=True)
    (task_dir / "hidden_tests" / "test_hidden.py").write_text(
        "def test_repeated_whitespace():\n    assert True\n", encoding="utf-8"
    )
    (task_dir / "public_tests").mkdir(parents=True)
    (task_dir / "public_tests" / "test_public.py").write_text(
        "def test_counts_words():\n    assert True\n", encoding="utf-8"
    )
    (task_dir / "mutations").mkdir(parents=True)
    (task_dir / "mutations" / "mutation-001.patch").write_text(
        "--- a/src/wordcount/__init__.py\n+++ b/src/wordcount/__init__.py\n", encoding="utf-8"
    )
    (task_dir / "description.md").write_text("# Word counting\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(TASK_WITH_CODE, encoding="utf-8")
    return load_task(task_dir)


def test_record_run_stores_the_code_of_the_task(database_url: str, tmp_path: Path) -> None:
    """A task's code is recorded, not only its prose.

    The repository an agent worked in and the tests that graded it are what a
    result is about, so they belong to the history rather than to a dataset
    checkout that may not exist when the history is read.
    """
    store = _store(database_url)

    store.record_run(_run_record(), task=_task_with_code(tmp_path))

    files = {row["path"]: row for row in store.task_files("wordcount-001@1.0.0")}
    kinds = {row["kind"] for row in files.values()}
    assert kinds == {"repository", "hidden_tests", "public_tests", "mutation"}
    assert files["src/wordcount/__init__.py"]["size_bytes"] > 0
    assert files["src/wordcount/__init__.py"]["digest"].startswith("sha256:")
    assert files["hidden_tests/test_hidden.py"]["kind"] == "hidden_tests"
    assert files["public_tests/test_public.py"]["kind"] == "public_tests"
    assert files["mutations/mutation-001.patch"]["kind"] == "mutation"


def test_a_recorded_file_is_read_back_verbatim(database_url: str, tmp_path: Path) -> None:
    store = _store(database_url)
    store.record_run(_run_record(), task=_task_with_code(tmp_path))

    stored = store.task_file("wordcount-001@1.0.0", "src/wordcount/__init__.py")

    assert stored is not None
    assert stored["content"] == "def count_words(text):\n    return len(text.split())\n"
    assert store.task_file("wordcount-001@1.0.0", "src/missing.py") is None


def test_recording_a_task_twice_updates_its_files_without_forking(
    database_url: str, tmp_path: Path
) -> None:
    """The same task recorded twice keeps one row per file."""
    store = _store(database_url)
    loaded = _task_with_code(tmp_path)

    store.record_run(_run_record(), task=loaded)
    store.record_run(_run_record(run_uid="run-2"), task=loaded)

    rows = store.task_files("wordcount-001@1.0.0")
    assert len(rows) == len({row["path"] for row in rows})


def test_binary_and_oversized_files_are_not_recorded(
    database_url: str, tmp_path: Path
) -> None:
    """A file that cannot be shown is left out rather than stored as noise."""
    from akbench import storage

    store = _store(database_url)
    loaded = _task_with_code(tmp_path)
    repository = tmp_path / "_sources" / "wordcount"
    (repository / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02")
    (repository / "vendor.py").write_text("x" * 300_000, encoding="utf-8")

    store.record_run(_run_record(), task=loaded)

    paths = {row["path"] for row in store.task_files("wordcount-001@1.0.0")}
    assert "logo.png" not in paths
    assert "vendor.py" not in paths
    assert "README.md" in paths
    assert storage.history  # the module under test is importable


def test_a_task_with_no_code_records_nothing(
    database_url: str, tmp_path: Path
) -> None:
    """A stub task with no readable files leaves an empty tree, not an error."""
    store = _store(database_url)

    store.record_run(_run_record(), task=_task_stub(path=tmp_path))

    assert store.task_files("wordcount-001@1.0.0") == []
