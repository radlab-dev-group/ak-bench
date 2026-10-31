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


def _task_stub(digest: str = "sha256:task") -> SimpleNamespace:
    repository = SimpleNamespace(source="https://example.test/wc.git", ref="abc1234")
    body = SimpleNamespace(repository=repository)
    descriptor = SimpleNamespace(
        id="wordcount-001",
        version="1.0.0",
        category="bug_fix",
        difficulty="easy",
        evaluator="pytest",
        task=body,
    )
    return SimpleNamespace(uid="wordcount-001@1.0.0", digest=digest, task=descriptor)


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


def test_record_run_creates_the_task_and_repository_rows(database_url: str) -> None:
    store = _store(database_url)

    store.record_run(_run_record(), task=_task_stub())

    with session_scope(create_db_engine(database_url)) as session:
        from akbench.storage.models import Repository, Task

        task = session.scalar(select(Task))
        assert task.uid == "wordcount-001@1.0.0"
        assert task.evaluator == "pytest"
        assert task.base_commit == "abc1234"
        repository = session.scalar(select(Repository))
        assert repository.source == "https://example.test/wc.git"


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
