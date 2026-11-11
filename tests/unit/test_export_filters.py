"""The export filters: each one removes what it declares, and says so.

A switch that quietly took more than it promised would be worse than no switch
at all — the reader of a reduced export could not tell which number was
measured and which was withheld. These tests pin the boundary from both sides:
what each flag removes, and what it is forbidden from touching.
"""

from __future__ import annotations

import json

from akbench.export.exporter import build_export
from akbench.export.filters import (
    WITHHELD,
    ExportFilters,
    Withheld,
    filter_document,
    filter_payload,
    is_diff_artifact,
    is_trace_artifact,
    without_diffs,
    without_prompts,
)
from akbench.reporting.data import HistoryData


def run(**overrides) -> dict:
    row = {
        "uid": "run-1",
        "task_uid": "wordcount-001",
        "status": "completed",
        "error_message": None,
        "observations": {"total_tokens": 40, "final_message": "I fixed the parser."},
        "evaluation": {"verdict": "passed", "score": 1.0, "total": 3},
        "artifacts": [
            {"filename": "run_record.json", "kind": "run_record", "checksum": "sha256:a"},
            {"filename": "agent_trace.jsonl", "kind": "agent_trace", "checksum": "sha256:b"},
            {"filename": "tool_calls.jsonl", "kind": "tool_calls", "checksum": "sha256:c"},
            {"filename": "diff.patch", "kind": "diff", "checksum": "sha256:d"},
        ],
    }
    row.update(overrides)
    return row


def document(**overrides) -> dict:
    doc = {
        "experiment": {"uid": "exp-1", "title": "One"},
        "runs": [run()],
        "artifacts": [
            {"run_uid": "run-1", "path": "/x/agent_trace.jsonl", "kind": "agent_trace"},
            {"run_uid": "run-1", "path": "/x/diff.patch", "kind": "diff"},
            {"run_uid": "run-1", "path": "/x/run_record.json", "kind": "run_record"},
        ],
        "metrics": [{"metric": "success_rate", "value": 1.0}],
    }
    doc.update(overrides)
    return doc


def names(artifacts: list[dict]) -> set[str]:
    return {str(item.get("filename") or item.get("path")).split("/")[-1] for item in artifacts}


# ------------------------------------------------------------------ naming


def test_traces_and_diffs_are_recognised_by_name_and_by_kind() -> None:
    assert is_trace_artifact("agent_trace.jsonl")
    assert is_trace_artifact("tool_calls.jsonl")
    assert is_trace_artifact("whatever.jsonl", "trace")
    assert not is_trace_artifact("run_record.json")
    assert not is_trace_artifact("evaluation.json", "evaluation")

    assert is_diff_artifact("diff.patch")
    assert is_diff_artifact("solution_diff.patch")
    assert is_diff_artifact("anything", "diff")
    assert not is_diff_artifact("run_record.json")


# ------------------------------------------------------------------ prompts


def test_no_prompts_takes_the_agents_text_and_leaves_the_result() -> None:
    """The agent's words go; the verdict, the score and the timings stay."""
    filtered, withheld = filter_document(document(), ExportFilters(include_prompts=False))

    row = filtered["runs"][0]
    assert row["observations"]["final_message"] == WITHHELD
    assert row["evaluation"] == {"verdict": "passed", "score": 1.0, "total": 3}
    assert row["observations"]["total_tokens"] == 40
    assert row["status"] == "completed"
    assert withheld["filters"] == ["prompts"]
    assert {"kind": "prompt-fields", "count": 1} in withheld["withheld"]


def test_no_prompts_does_not_touch_artifacts_it_was_not_asked_about() -> None:
    filtered, _ = filter_document(document(), ExportFilters(include_prompts=False))

    assert names(filtered["runs"][0]["artifacts"]) == names(document()["runs"][0]["artifacts"])
    assert names(filtered["artifacts"]) == names(document()["artifacts"])


def test_without_prompts_keeps_the_shape_of_the_record() -> None:
    """The key survives holding a marker, so a reader sees there was a message."""
    stripped = without_prompts({"final_message": "hi", "keep": {"prompt": "task text"}})

    assert stripped == {"final_message": WITHHELD, "keep": {"prompt": WITHHELD}}


# -------------------------------------------------------------------- diffs


def test_no_diffs_takes_the_patch_and_keeps_the_score() -> None:
    filtered, withheld = filter_document(document(), ExportFilters(include_diffs=False))

    assert "diff.patch" not in names(filtered["runs"][0]["artifacts"])
    assert "run_record.json" in names(filtered["runs"][0]["artifacts"])
    assert filtered["runs"][0]["evaluation"]["score"] == 1.0
    assert "diff.patch" not in names(filtered["artifacts"])
    assert withheld["filters"] == ["diffs"]
    assert {"kind": "diffs", "count": 1} in withheld["withheld"]


def test_without_diffs_replaces_a_diff_field_in_place() -> None:
    stripped = without_diffs({"diff": "--- a\n+++ b\n", "score": 0.5})

    assert stripped == {"diff": WITHHELD, "score": 0.5}


# ------------------------------------------------------------------ traces


def test_no_traces_takes_the_step_by_step_files_and_keeps_their_metrics() -> None:
    filtered, withheld = filter_document(document(), ExportFilters(include_traces=False))

    kept = names(filtered["runs"][0]["artifacts"])
    assert "agent_trace.jsonl" not in kept
    assert "tool_calls.jsonl" not in kept
    assert {"run_record.json", "diff.patch"} == kept
    assert filtered["runs"][0]["observations"]["total_tokens"] == 40
    assert withheld["filters"] == ["traces"]


def test_the_three_switches_compose() -> None:
    filtered, withheld = filter_document(
        document(), ExportFilters(include_prompts=False, include_diffs=False, include_traces=False)
    )

    row = filtered["runs"][0]
    assert names(row["artifacts"]) == {"run_record.json"}
    assert row["observations"]["final_message"] == WITHHELD
    assert row["evaluation"]["verdict"] == "passed"
    assert filtered["metrics"] == document()["metrics"]
    assert set(withheld["filters"]) == {"prompts", "diffs", "traces"}


def test_an_export_with_no_flags_is_untouched_apart_from_the_note() -> None:
    narrowed, withheld = filter_document(document(), ExportFilters())

    assert narrowed == document()
    assert withheld == {}


def test_the_switch_names_are_the_ones_the_cli_prints() -> None:
    assert ExportFilters().active == ()
    assert ExportFilters(include_prompts=False).active == ("prompts",)
    assert ExportFilters(include_diffs=False, include_traces=False).active == ("diffs", "traces")


# ----------------------------------------------------------------- exporter


def test_build_export_records_the_filters_and_survives_round_trip() -> None:
    """A narrowed document is still valid JSON: an export is read by scripts."""
    data = HistoryData(
        experiments=[{"uid": "exp-1", "title": "One", "type": "configuration"}],
        runs=[run(experiment_uid="exp-1", variant_uid="v1")],
        variants={"exp-1": [{"uid": "v1", "experiment_uid": "exp-1"}]},
    )

    bundle = build_export(data, "exp-1", filters=ExportFilters(include_traces=False))

    assert bundle.filters == ("traces",)
    assert bundle.withheld
    payload = json.loads(json.dumps(bundle.document))
    kept = {item["filename"] for item in payload["runs"][0]["artifacts"]}
    assert "agent_trace.jsonl" not in kept
    assert "run_record.json" in kept


def test_filter_payload_drops_a_file_the_filters_excluded() -> None:
    filters = ExportFilters(include_traces=False)
    assert filter_payload("agent_trace.jsonl", b"some lines\n", filters) is None
    assert filter_payload("run_record.json", b"{}", filters) == b"{}"


def test_filter_payload_strips_named_fields_from_a_json_record() -> None:
    record = b'{"final_message": "the answer", "score": 1, "diff": "a patch"}'
    filters = ExportFilters()
    withheld = Withheld()
    result = filter_payload("run_record.json", record, filters, withheld)
    assert result is not None and json.loads(result) == json.loads(record)

    filters = ExportFilters(include_prompts=False, include_diffs=False)
    withheld = Withheld()
    result = filter_payload("run_record.json", record, filters, withheld)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["final_message"] == WITHHELD
    assert parsed["diff"] == WITHHELD
    assert parsed["score"] == 1
    assert withheld.as_dict()

    plain = b"not json at all"
    assert filter_payload("notes.txt", plain, filters) == plain
    filters = ExportFilters(include_prompts=False)
    assert filter_payload("run_record.json", b"not json", filters) == b"not json"
