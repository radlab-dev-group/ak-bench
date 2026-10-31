"""The reporting layer: honest numbers, escaped HTML, a tree that links up.

The reports are the face of the project, so the tests guard the two ways a
report can lie: a number that stands for less than it appears to, and markup
from a run record that renders as content.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from akbench.reporting.data import (
    build_experiment_report,
    build_task_report,
    collect_history,
    dashboard,
    duration_seconds,
    summarize_runs,
    unverified_configurations,
)
from akbench.reporting.render import (
    NOT_MEASURED,
    duration,
    esc,
    number,
    percent,
    write_report_tree,
)
from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import upgrade


def _store(database_url: str) -> HistoryStore:
    upgrade(database_url)
    return HistoryStore(create_db_engine(database_url))


def _task_stub(uid: str = "wordcount-001@1.0.0") -> SimpleNamespace:
    repository = SimpleNamespace(source="https://example.test/wc.git", ref="abc1234")
    return SimpleNamespace(
        uid=uid,
        digest="sha256:task",
        task=SimpleNamespace(
            id=uid.split("@")[0],
            version="1.0.0",
            category="bug_fix",
            difficulty="easy",
            evaluator="pytest",
            task=SimpleNamespace(repository=repository),
        ),
    )


def _run(run_uid: str, *, verdict: str | None = "passed", **overrides: object) -> dict:
    record: dict = {
        "run_uid": run_uid,
        "task_uid": "wordcount-001@1.0.0",
        "agent_id": "codex",
        "agent_version": "0.1.0",
        "mode": "router",
        "runtime_id": "llm-router",
        "state": "completed",
        "started_at": "2026-10-30T10:00:00+00:00",
        "finished_at": "2026-10-30T10:02:00+00:00",
        "observations": {"total_tokens": 100, "input_tokens": 60},
    }
    if verdict is not None:
        record["evaluation"] = {
            "verdict": verdict,
            "score": 1.0 if verdict == "passed" else 0.0,
            "passed": 1 if verdict == "passed" else 0,
            "failed": 0 if verdict == "passed" else 1,
            "total": 1,
        }
    record.update(overrides)
    return record


def _seeded(database_url: str) -> HistoryStore:
    store = _store(database_url)
    store.record_plan(
        experiment_uid="demo@1.0.0",
        title="demo",
        experiment_type="configuration",
        descriptor_id="demo",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg",
        variants=[
            {"uid": "v-1", "index": 0, "values": {"knowledge_enabled": False}, "is_baseline": True},
            {"uid": "v-2", "index": 1, "values": {"knowledge_enabled": True}},
        ],
        snapshots=[{"kind": "agent", "id": "codex", "version": "1.0.0", "digest": "sha256:agent"}],
    )
    store.record_run(
        _run("run-pass"),
        experiment_uid="demo@1.0.0",
        variant_uid="v-1",
        task=_task_stub(),
        observed_model={"observed_model": "gpt-5", "verification_status": "unverified"},
    )
    store.record_run(
        _run("run-fail", verdict="failed", failure_class="assertion"),
        experiment_uid="demo@1.0.0",
        variant_uid="v-2",
        task=_task_stub(),
    )
    store.record_plugin_observations(
        "run-pass",
        [
            {
                "plugin_id": "agentic-knowledge",
                "plugin_version": "1.2.0",
                "enabled": True,
                "state": {"verification_status": "unverified"},
            }
        ],
    )
    store.record_experiment_metrics(
        "demo@1.0.0",
        {
            "task_success": {
                "group": "quality",
                "unit": "ratio",
                "runs": 2,
                "measured": 2,
                "availability": 1.0,
                "mean": 0.5,
                "minimum": 0.0,
                "maximum": 1.0,
                "deviation": 0.7071,
            }
        },
    )
    return store


# ------------------------------------------------------------ number formats


def test_absent_values_say_so_rather_than_reading_as_zero() -> None:
    assert number(None) == NOT_MEASURED
    assert percent(None) == NOT_MEASURED
    assert duration(None) == NOT_MEASURED
    assert number(1234) == "1,234"
    assert number(1.5, digits=2) == "1.50"
    assert percent(0.25) == "25.0%"


def test_duration_scales_to_minutes_and_hours() -> None:
    assert duration(30) == "30.0 s"
    assert duration(90) == "1 m 30 s"
    assert duration(3600) == "1 h 0 m"


def test_html_escaping_of_recorded_text() -> None:
    assert esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_duration_seconds_needs_both_ends() -> None:
    started_only = {"started_at": None, "finished_at": "2026-10-30T10:00:00+00:00"}
    assert duration_seconds(started_only) is None
    assert (
        duration_seconds(
            {"started_at": "2026-10-30T10:00:00+00:00", "finished_at": "2026-10-30T10:00:30+00:00"}
        )
        == 30.0
    )


# ----------------------------------------------------------------- numbers


def test_summary_counts_evaluation_separately_from_runs() -> None:
    runs = [{"run_uid": "a"}, {"run_uid": "b", "evaluation": {"verdict": "passed"}}]

    summary = summarize_runs(runs)
    assert summary["runs"] == 2
    assert summary["evaluated"] == 1
    assert summary["passed"] == 1
    assert summary["success_rate"] == 1.0


def test_summary_of_nothing_measures_nothing() -> None:
    summary = summarize_runs([])
    assert summary["success_rate"] is None
    assert summary["mean_duration_seconds"] is None
    assert summary["total_tokens"] is None


def test_dashboard_groups_by_agent_runtime_and_task_attribute(database_url: str) -> None:
    data = collect_history(_seeded(database_url))

    stats = dashboard(data)
    assert stats["experiments"] == 1
    assert stats["runs"] == 2
    assert stats["success_rate"] == 0.5
    assert stats["verdicts"] == {"passed": 1, "failed": 1}
    assert stats["total_tokens"] == 200
    assert [row["category"] for row in stats["by_category"]] == ["bug_fix"]
    assert [row["difficulty"] for row in stats["by_difficulty"]] == ["easy"]
    assert stats["agents"][0]["agent"] == "codex@0.1.0"
    assert stats["agents"][0]["passed"] == 1
    assert stats["runtimes"][0]["runtime"] == "llm-router"


def test_dashboard_reports_cost_as_not_recorded(database_url: str) -> None:
    stats = dashboard(collect_history(_seeded(database_url)))

    assert stats["cost"]["available"] is False
    assert "guess" in stats["cost"]["reason"]


def test_unverified_configurations_are_listed_not_dropped(database_url: str) -> None:
    data = collect_history(_seeded(database_url))

    findings = unverified_configurations(data)
    kinds = {(item["kind"], item["subject"], item["status"]) for item in findings}
    assert ("plugin", "agentic-knowledge", "unverified") in kinds
    assert ("model", "gpt-5", "unverified") in kinds


# --------------------------------------------------------------- the pages


def test_report_tree_contains_the_expected_pages(database_url: str, tmp_path: Path) -> None:
    data = collect_history(_seeded(database_url))

    written = write_report_tree(
        tmp_path / "reports", data, generated_at="2026-10-31T12:00:00+00:00"
    )
    root = tmp_path / "reports"
    relative = {str(path.relative_to(root)) for path in written}
    assert "index.html" in relative
    assert "assets/style.css" in relative
    assert "experiments/demo@1.0.0/index.html" in relative
    assert "tasks/wordcount-001@1.0.0/index.html" in relative
    listings = {
        "agents/index.html",
        "runtimes/index.html",
        "plugins/index.html",
        "models/index.html",
    }
    assert listings <= relative


def test_pages_link_to_the_stylesheet_at_their_own_depth(database_url: str, tmp_path: Path) -> None:
    data = collect_history(_seeded(database_url))

    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"
    assert 'href="assets/style.css"' in (root / "index.html").read_text(encoding="utf-8")
    experiment = (root / "experiments" / "demo@1.0.0" / "index.html").read_text(encoding="utf-8")
    assert 'href="../../assets/style.css"' in experiment
    assert '{{' not in experiment


def test_experiment_page_shows_pass_and_failure(
    database_url: str, tmp_path: Path
) -> None:
    data = collect_history(_seeded(database_url))

    write_report_tree(tmp_path / "reports", data)
    page = (
        tmp_path / "reports" / "experiments" / "demo@1.0.0" / "index.html"
    ).read_text(encoding="utf-8")
    assert "run-pass" in page
    assert "run-fail" in page
    assert "assertion" in page
    assert "agentic-knowledge" in page
    assert "knowledge_enabled=True" in page
    assert "0.7071" in page


def test_task_page_lists_every_run_of_the_task(database_url: str, tmp_path: Path) -> None:
    data = collect_history(_seeded(database_url))

    write_report_tree(tmp_path / "reports", data)
    page = (
        tmp_path / "reports" / "tasks" / "wordcount-001@1.0.0" / "index.html"
    ).read_text(encoding="utf-8")
    assert "run-pass" in page and "run-fail" in page
    assert "bug_fix" in page


def test_an_empty_history_still_renders(database_url: str, tmp_path: Path) -> None:
    store = _store(database_url)

    data = collect_history(store)
    written = write_report_tree(tmp_path / "reports", data)

    index = next(path for path in written if path.name == "index.html")
    body = index.read_text(encoding="utf-8")
    assert "nothing recorded" in body
    assert NOT_MEASURED in body


def test_report_objects_carry_their_own_scoped_findings(database_url: str) -> None:
    data = collect_history(_seeded(database_url))

    experiment = build_experiment_report(data, "demo@1.0.0")
    task = build_task_report(data, "wordcount-001@1.0.0")
    assert experiment.summary["runs"] == 2
    assert len(experiment.variants) == 2
    assert experiment.snapshots[0]["digest"] == "sha256:agent"
    assert experiment.metrics[0]["metric"] == "task_success"
    assert any(item["kind"] == "plugin" for item in experiment.unverified)
    assert task.summary["runs"] == 2
