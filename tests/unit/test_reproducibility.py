"""Reproducibility: identical conditions, verified from the recorded history.

The platform does not promise identical agent answers — a model is not a
function. It promises that the conditions of an experiment are identical and
that the record proves it: the same descriptors pinned, the same variant
configuration, the same task digest, and artifacts that still match their
checksums.

These tests build the same history twice and check that the two are
indistinguishable in everything a reproduction is defined by, and that a
change to one pinned descriptor does show up.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from akbench.storage.db import create_db_engine, session_scope
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import upgrade
from akbench.storage.models import DescriptorSnapshot, ExperimentVariant


def _task_stub() -> SimpleNamespace:
    repository = SimpleNamespace(source="https://example.test/wc.git", ref="abc1234")
    return SimpleNamespace(
        uid="wordcount-001@1.0.0",
        digest="sha256:task",
        task=SimpleNamespace(
            id="wordcount-001",
            version="1.0.0",
            category="bug_fix",
            difficulty="easy",
            evaluator="pytest",
            task=SimpleNamespace(repository=repository),
        ),
    )


def _seed(database_url: str) -> HistoryStore:
    upgrade(database_url)
    store = HistoryStore(create_db_engine(database_url))
    store.record_plan(
        experiment_uid="demo@1.0.0",
        title="demo",
        experiment_type="configuration",
        descriptor_id="demo",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg",
        variants=[
            {
                "uid": "v-1",
                "index": 0,
                "values": {"knowledge_enabled": False},
                "config_hash": "sha256:v1",
                "is_baseline": True,
            },
            {
                "uid": "v-2",
                "index": 1,
                "values": {"knowledge_enabled": True},
                "config_hash": "sha256:v2",
            },
        ],
        snapshots=[
            {"kind": "agent", "id": "codex", "version": "1.0.0", "digest": "sha256:agent"},
            {"kind": "runtime", "id": "llm-router", "version": "1.0.0", "digest": "sha256:router"},
        ],
    )
    for number in (1, 2):
        store.record_run(
            {
                "run_uid": f"run-{number}",
                "task_uid": "wordcount-001@1.0.0",
                "agent_id": "codex",
                "agent_version": "0.1.0",
                "mode": "router",
                "runtime_id": "llm-router",
                "state": "completed",
                "started_at": "2026-10-30T10:00:00+00:00",
                "finished_at": "2026-10-30T10:00:30+00:00",
                "observations": {"total_tokens": 50 + number},
                "evaluation": {
                    "verdict": "passed",
                    "score": 1.0,
                    "passed": 1,
                    "failed": 0,
                    "total": 1,
                },
            },
            experiment_uid="demo@1.0.0",
            variant_uid=f"v-{number}",
            task=_task_stub(),
            repetition=number,
        )
    return store


def _conditions(store: HistoryStore) -> dict[str, object]:
    """Everything a reproduction is defined by, read back from one history."""
    experiment = store.experiments()[0]
    runs = store.runs()
    with session_scope(store.engine) as session:
        variants = {
            row.uid: (row.values_json, row.config_hash, row.is_baseline)
            for row in session.scalars(select(ExperimentVariant)).all()
        }
        snapshots = {
            (row.kind, row.descriptor_id, row.version): row.digest
            for row in session.scalars(select(DescriptorSnapshot).order_by(DescriptorSnapshot.id))
        }
    return {
        "experiment": {
            key: experiment[key]
            for key in ("uid", "descriptor", "config_hash", "type")
        },
        "variants": variants,
        "snapshots": snapshots,
        "runs": [
            {
                "task_uid": run["task_uid"],
                "agent": run["agent"],
                "runtime": run["runtime_id"],
                "variant": run["variant_uid"],
                "repetition": run["repetition"],
            }
            for run in runs
        ],
    }


def test_two_histories_from_the_same_plan_are_indistinguishable(tmp_path: Path) -> None:
    first = _seed(f"sqlite:///{tmp_path / 'first.sqlite'}")
    second = _seed(f"sqlite:///{tmp_path / 'second.sqlite'}")

    assert _conditions(first) == _conditions(second)


def test_a_changed_pinned_descriptor_shows_up(tmp_path: Path) -> None:
    first = _seed(f"sqlite:///{tmp_path / 'first.sqlite'}")
    second = _seed(f"sqlite:///{tmp_path / 'second.sqlite'}")

    with session_scope(second.engine) as session:
        for row in session.scalars(select(DescriptorSnapshot)).all():
            if row.kind == "agent":
                row.version = "1.1.0"
                row.digest = "sha256:agent-v2"

    assert _conditions(first) != _conditions(second)


def test_repeated_planning_does_not_fork_the_history(database_url: str) -> None:
    store = _seed(database_url)

    store.record_plan(experiment_uid="demo@1.0.0", variants=[{"uid": "v-1"}])

    assert len(store.experiments()) == 1
    assert len(store.variants("demo@1.0.0")) == 2  # the planned variants survive


def test_repeated_recording_does_not_duplicate_a_run(database_url: str) -> None:
    store = _seed(database_url)

    store.record_run(
        {
            "run_uid": "run-1",
            "task_uid": "wordcount-001@1.0.0",
            "state": "completed",
            "observations": {"total_tokens": 999},
        },
        experiment_uid="demo@1.0.0",
        task=_task_stub(),
    )

    runs = store.runs("demo@1.0.0")
    assert len(runs) == 2
    assert sum(1 for run in runs if run["uid"] == "run-1") == 1


def test_artifact_verification_is_a_check_a_reader_can_repeat(
    database_url: str, tmp_path: Path
) -> None:
    store = _seed(database_url)
    artifact = tmp_path / "evaluation.json"
    artifact.write_text('{"verdict": "passed"}\n', encoding="utf-8")
    store.register_artifacts("run-1", [artifact])

    assert all(item["ok"] for item in store.verify_artifacts("run-1"))

    artifact.write_text('{"verdict": "failed"}\n', encoding="utf-8")

    assert any(item["reason"] == "checksum mismatch" for item in store.verify_artifacts("run-1"))
