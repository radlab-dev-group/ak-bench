"""The export: the same facts in three formats, with secrets screened out.

The screen is the part worth testing hardest. A run record contains agent
output, and agent output can contain a key the agent printed; nothing in the
export may carry it. The tests check both halves: the secret is gone, and the
export says something was withheld.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

from akbench.export.exporter import build_export, to_csv, to_json, write_bundle
from akbench.export.redact import REDACTION, redact
from akbench.reporting.data import HistoryData
from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import upgrade


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


def _data(database_url: str) -> HistoryData:
    upgrade(database_url)
    store = HistoryStore(create_db_engine(database_url))
    store.record_plan(
        experiment_uid="demo@1.0.0",
        title="demo",
        experiment_type="configuration",
        descriptor_id="demo",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg",
        variants=[{"uid": "v-1", "index": 0, "values": {"k": True}, "is_baseline": True}],
    )
    store.record_run(
        {
            "run_uid": "run-1",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "0.1.0",
            "mode": "direct",
            "state": "completed",
            "started_at": "2026-10-30T10:00:00+00:00",
            "finished_at": "2026-10-30T10:00:30+00:00",
            "observations": {"total_tokens": 50},
            "evaluation": {"verdict": "passed", "score": 1.0, "passed": 1, "failed": 0, "total": 1},
        },
        experiment_uid="demo@1.0.0",
        variant_uid="v-1",
        task=_task_stub(),
    )
    return HistoryData(
        experiments=store.experiments(),
        runs=store.runs(),
        tasks=store.tasks(),
        plugins=store.plugin_observations(),
        models=store.model_observations(),
        metrics={"demo@1.0.0": store.metrics("demo@1.0.0")},
        variants={"demo@1.0.0": store.variants("demo@1.0.0")},
        snapshots={"demo@1.0.0": store.snapshots("demo@1.0.0")},
    )


# ------------------------------------------------------------------- screen


def test_a_key_in_the_text_is_replaced_and_counted() -> None:
    payload = {"output": "loaded sk-abcdefghij0123456789XYZ from env"}

    screened, redactions = redact(payload)

    assert "sk-abcdefghij0123456789XYZ" not in screened["output"]
    assert REDACTION.format(kind="openai-key") in screened["output"]
    assert {"kind": "openai-key", "count": 1} in redactions


def test_a_secret_valued_field_is_never_exported() -> None:
    payload = {"config": {"OPENAI_API_KEY": "anything at all", "model": "gpt-5"}}

    screened, redactions = redact(payload)

    assert screened["config"]["OPENAI_API_KEY"] == REDACTION.format(kind="secret-field")
    assert screened["config"]["model"] == "gpt-5"
    assert any(row["kind"] == "secret-field" for row in redactions)


def test_a_set_secret_environment_value_is_removed_from_anywhere() -> None:
    payload = {"trace": "router answered with LLMROUTERSECRET42"}

    screened, redactions = redact(payload, environment={"LLM_ROUTER_API_KEY": "LLMROUTERSECRET42"})

    assert "LLMROUTERSECRET42" not in screened["trace"]
    assert "[REDACTED:" in screened["trace"]
    assert any(row["kind"] == "llm_router_api_key-env" for row in redactions)


def test_an_authorization_header_and_a_pem_block_are_removed() -> None:
    payload = {
        "request": "Authorization: Bearer abcdef1234567890",
        "key_file": "-----BEGIN RSA PRIVATE KEY-----",
    }

    screened, redactions = redact(payload)

    assert "Bearer" not in screened["request"]
    assert "PRIVATE KEY" not in screened["key_file"]
    kinds = {row["kind"] for row in redactions}
    assert {"authorization-header", "pem-key"} <= kinds


def test_ordinary_text_is_left_alone() -> None:
    payload = {"detail": "test_wordcount failed with exit code 1 after 3 tests"}

    screened, redactions = redact(payload)

    assert screened["detail"] == payload["detail"]
    assert redactions == []


# ------------------------------------------------------------------ exports


def test_json_export_carries_the_whole_experiment(database_url: str) -> None:
    data = _data(database_url)

    bundle = build_export(data, "demo@1.0.0")
    document = json.loads(to_json(bundle))

    assert document["experiment"]["uid"] == "demo@1.0.0"
    assert document["experiment"]["config_hash"] == "sha256:cfg"
    assert [variant["uid"] for variant in document["variants"]] == ["v-1"]
    assert document["runs"][0]["uid"] == "run-1"
    assert document["summary"]["runs"] == 1
    assert "generated_at" in document


def test_csv_export_has_one_row_per_run_with_the_essentials(database_url: str) -> None:
    data = _data(database_url)

    rows = list(csv.DictReader(io.StringIO(to_csv(build_export(data, "demo@1.0.0")))))

    assert len(rows) == 1
    row = rows[0]
    assert row["run_uid"] == "run-1"
    assert row["verdict"] == "passed"
    assert row["score"] == "1.0"
    assert row["duration_seconds"] == "30.0"
    assert row["total_tokens"] == "50"
    assert row["task_uid"] == "wordcount-001@1.0.0"


def test_write_bundle_writes_the_requested_formats(database_url: str, tmp_path: Path) -> None:
    data = _data(database_url)
    bundle = build_export(data, "demo@1.0.0")

    written = write_bundle(bundle, data, output_dir=tmp_path / "exports", formats=("json", "csv"))

    names = sorted(path.name for path in written)
    assert names == ["demo@1.0.0.json", "demo@1.0.0.runs.csv"]
    assert all(path.is_file() for path in written)


def test_html_export_is_the_standalone_experiment_page(database_url: str, tmp_path: Path) -> None:
    data = _data(database_url)
    bundle = build_export(data, "demo@1.0.0")

    written = write_bundle(bundle, data, output_dir=tmp_path, formats=("html",))

    page = written[0].read_text(encoding="utf-8")
    assert page.startswith("<!DOCTYPE html>")
    assert "run-1" in page
    assert "<style>" in page
    assert "{{css}}" not in page


def test_an_export_never_carries_a_key_that_was_in_a_run(database_url: str) -> None:
    upgrade(database_url)
    store = HistoryStore(create_db_engine(database_url))
    store.record_plan(experiment_uid="leaky@1.0.0", title="leaky")
    store.record_run(
        {
            "run_uid": "run-leak",
            "task_uid": "t@1.0.0",
            "state": "failed",
            "error_message": "agent printed sk-abcdefghij0123456789XYZ while running",
        },
        experiment_uid="leaky@1.0.0",
    )
    data = HistoryData(
        experiments=store.experiments(), runs=store.runs(), tasks=store.tasks()
    )

    assert "sk-abcdefghij0123456789XYZ" in data.runs[0]["error_message"]
    bundle = build_export(data, "leaky@1.0.0")

    assert "sk-abcdefghij0123456789XYZ" not in to_json(bundle)
    assert "sk-abcdefghij0123456789XYZ" not in to_csv(bundle)
    assert any(row["kind"] == "openai-key" for row in bundle.redactions)
