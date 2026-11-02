"""The reporting layer: honest numbers, escaped HTML, a tree that links up.

The reports are the face of the project, so the tests guard the two ways a
report can lie: a number that stands for less than it appears to, and markup
from a run record that renders as content.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from akbench.reporting.data import (
    build_experiment_report,
    build_task_report,
    build_variant_report,
    collect_history,
    configuration_ranking,
    dashboard,
    duration_seconds,
    summarize_runs,
    unverified_configurations,
)
from akbench.reporting.render import (
    NOT_MEASURED,
    STYLE,
    duration,
    esc,
    number,
    percent,
    render_experiment,
    render_index,
    render_variant,
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


def test_pages_link_to_the_stylesheet_at_deeper_uids(database_url: str, tmp_path: Path) -> None:
    """An experiment uid may contain a slash (``adhoc/<agent>``); the page one
    level deeper still reaches the stylesheet."""
    store = _seeded(database_url)
    store.record_plan(
        experiment_uid="adhoc/codex",
        title="adhoc codex",
        experiment_type="adhoc",
        descriptor_id="codex",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg",
        variants=[{"uid": "v-1", "index": 0, "values": {}, "is_baseline": True}],
        snapshots=[{"kind": "agent", "id": "codex", "version": "1.0.0", "digest": "sha256:agent"}],
    )
    store.record_run(
        _run("run-adhoc"),
        experiment_uid="adhoc/codex",
        variant_uid="v-1",
        task=_task_stub(),
    )

    write_report_tree(tmp_path / "reports", collect_history(store))
    page = (tmp_path / "reports" / "experiments" / "adhoc" / "codex" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'href="../../../assets/style.css"' in page
    page_directory = tmp_path / "reports" / "experiments" / "adhoc" / "codex"
    linked = (page_directory / "../../../assets/style.css").resolve()
    assert linked == (tmp_path / "reports" / "assets" / "style.css").resolve()
    assert linked.is_file()


# ------------------------------------------------------------------- ranking


def _run_for(
    run_uid: str,
    *,
    variant_uid: str,
    verdict: str | None = "passed",
    tokens: int | None = None,
    start: str = "2026-10-30T10:00:00+00:00",
    finish: str = "2026-10-30T10:01:00+00:00",
    agent: str = "codex@1.0.0",
    runtime: str = "llm-router",
    experiment_uid: str = "demo@1.0.0",
    task_uid: str = "wordcount-001@1.0.0",
) -> dict:
    run: dict = {
        "uid": run_uid,
        "experiment_uid": experiment_uid,
        "variant_uid": variant_uid,
        "task_uid": task_uid,
        "agent": agent,
        "runtime_id": runtime,
        "started_at": start,
        "finished_at": finish,
    }
    if verdict is not None:
        run["evaluation"] = {"verdict": verdict}
    if tokens is not None:
        run["observations"] = {"total_tokens": tokens}
    return run


def _two_variants() -> tuple[list[dict], dict[str, list[dict]]]:
    variants = [
        {"uid": "v-on", "values": {"knowledge_enabled": True}, "is_baseline": False},
        {"uid": "v-off", "values": {"knowledge_enabled": False}, "is_baseline": True},
    ]
    runs = [
        _run_for("a", variant_uid="v-on", tokens=100),
        _run_for("b", variant_uid="v-on", tokens=300),
        _run_for(
            "c",
            variant_uid="v-off",
            verdict="failed",
            tokens=400,
            finish="2026-10-30T10:03:00+00:00",
        ),
    ]
    return runs, {"demo@1.0.0": variants}


def test_configuration_ranking_places_the_better_configuration_first() -> None:
    runs, variants = _two_variants()

    rows = configuration_ranking(runs, variants)

    assert [row["config"] for row in rows] == [
        "knowledge_enabled=True",
        "knowledge_enabled=False",
    ]
    assert [row["place"] for row in rows] == [1, 2]
    assert rows[0]["success_rate"] == 1.0
    assert rows[1]["success_rate"] == 0.0
    assert rows[0]["is_baseline"] is False
    assert rows[1]["is_baseline"] is True
    # the baseline has no delta to itself; the other row states its difference
    assert rows[1]["vs_baseline"] == ""
    assert "success +100%" in rows[0]["vs_baseline"]
    assert "time 0.33x" in rows[0]["vs_baseline"]


def test_configuration_ranking_shares_a_place_and_skips_the_next_one() -> None:
    """A tie is a tie in every deciding measure, or it is not shared at all."""
    runs, variants = _two_variants()
    for run in runs:
        run["evaluation"] = {"verdict": "passed"}
        run["started_at"] = "2026-10-30T10:00:00+00:00"
        run["finished_at"] = "2026-10-30T10:01:00+00:00"
        run["observations"] = {"total_tokens": 100}

    rows = configuration_ranking(runs, variants)

    assert [row["place"] for row in rows] == [1, 1]
    # fully tied rows keep their deterministic order: first start, then name
    assert [row["config"] for row in rows] == [
        "knowledge_enabled=False",
        "knowledge_enabled=True",
    ]


def test_a_configuration_without_evaluation_holds_no_place() -> None:
    """A run that was never scored says nothing: it is not a failure either."""
    runs, variants = _two_variants()
    for run in runs:
        if run["variant_uid"] == "v-off":
            run.pop("evaluation")

    rows = configuration_ranking(runs, variants)

    assert [(row["config"], row["place"]) for row in rows] == [
        ("knowledge_enabled=True", 1),
        ("knowledge_enabled=False", None),
    ]
    assert rows[1]["success_rate"] is None
    # the other row cannot be compared against a baseline with no measured rate
    assert "not comparable" in rows[0]["vs_baseline"]


def test_ranking_of_nothing_is_empty() -> None:
    assert configuration_ranking([], {}) == []


def test_the_same_configuration_in_two_experiments_is_one_row() -> None:
    """A configuration is the values with their agent and runtime, nothing else.

    A second recording of the same experiment, or the same configuration in
    another experiment, adds its runs to the one row it already has.
    """
    variants = {
        "demo@1.0.0": [
            {"uid": "v-on", "values": {"knowledge_enabled": True}, "is_baseline": False},
            {"uid": "v-off", "values": {"knowledge_enabled": False}, "is_baseline": True},
        ],
        "demo@2.0.0": [
            {"uid": "v-again", "values": {"knowledge_enabled": True}, "is_baseline": False},
            {"uid": "v-else", "values": {"knowledge_enabled": False}, "is_baseline": False},
        ],
    }
    runs = [
        _run_for("a", variant_uid="v-on", verdict="passed", tokens=100),
        _run_for("b", variant_uid="v-off", verdict="failed", tokens=200),
        _run_for(
            "c",
            variant_uid="v-again",
            verdict="passed",
            tokens=300,
            experiment_uid="demo@2.0.0",
            start="2026-10-31T09:00:00+00:00",
            finish="2026-10-31T09:01:00+00:00",
        ),
        _run_for(
            "d",
            variant_uid="v-else",
            verdict="passed",
            tokens=400,
            experiment_uid="demo@2.0.0",
            start="2026-10-31T10:00:00+00:00",
            finish="2026-10-31T10:01:00+00:00",
        ),
        _run_for(
            "e",
            variant_uid="v-else",
            verdict="passed",
            tokens=200,
            experiment_uid="demo@2.0.0",
            start="2026-10-31T10:02:00+00:00",
            finish="2026-10-31T10:03:00+00:00",
        ),
    ]

    rows = configuration_ranking(runs, variants)

    assert len(rows) == 2
    on = next(row for row in rows if row["config"] == "knowledge_enabled=True")
    off = next(row for row in rows if row["config"] == "knowledge_enabled=False")
    # the pool: every run of the configuration, from both experiments
    assert on["runs"] == 2
    assert on["evaluated"] == 2
    assert on["passed"] == 2
    assert on["success_rate"] == 1.0
    # the pool of the baseline: 1/2 in the first recording, 1/1 in the second,
    # pooled to 2/3 rather than averaged to 0.75
    assert off["runs"] == 3
    assert off["passed"] == 2
    assert off["success_rate"] == round(2 / 3, 6)
    assert off["mean_total_tokens"] == round(800 / 3, 6)
    # tokens are stated per run, because the pools have different sizes
    assert on["mean_total_tokens"] == 200
    assert on["total_tokens"] == 400
    assert on["experiments"] == ["demo@1.0.0", "demo@2.0.0"]
    assert on["recordings"] == 2
    assert off["experiments"] == ["demo@1.0.0", "demo@2.0.0"]
    assert off["recordings"] == 2
    # the row window spans both recordings
    assert on["first_started"] == "2026-10-30T10:00:00+00:00"
    assert on["last_finished"] == "2026-10-31T09:01:00+00:00"
    assert off["last_finished"] == "2026-10-31T10:03:00+00:00"


def test_the_same_values_under_another_agent_or_runtime_are_two_rows() -> None:
    variants = {
        "demo@1.0.0": [
            {"uid": "v-on", "values": {"knowledge_enabled": True}, "is_baseline": False},
            {
                "uid": "v-other-agent",
                "values": {"knowledge_enabled": True},
                "is_baseline": False,
            },
            {
                "uid": "v-other-runtime",
                "values": {"knowledge_enabled": True},
                "is_baseline": False,
            },
        ],
    }
    runs = [
        _run_for("a", variant_uid="v-on", tokens=100),
        _run_for("b", variant_uid="v-other-agent", tokens=200, agent="claude@2.0.0"),
        _run_for("c", variant_uid="v-other-runtime", tokens=300, runtime="direct"),
    ]

    rows = configuration_ranking(runs, variants)

    assert len(rows) == 3
    assert {(row["agent"], row["runtime"]) for row in rows} == {
        ("codex@1.0.0", "llm-router"),
        ("claude@2.0.0", "llm-router"),
        ("codex@1.0.0", "direct"),
    }
    assert all(row["runs"] == 1 for row in rows)


def test_a_run_of_an_unplanned_variant_is_not_ranked() -> None:
    """The ranking lists configurations; an unplanned run states none of them."""
    runs, variants = _two_variants()
    runs.append(_run_for("ghost", variant_uid="v-ghost", tokens=5))

    rows = configuration_ranking(runs, variants)

    assert len(rows) == 2
    assert {row["runs"] for row in rows} == {2, 1}
    assert sum(row["runs"] for row in rows) == 3



def test_experiment_page_shows_the_ranking_with_bars(database_url: str) -> None:
    data = collect_history(_seeded(database_url))

    page = render_experiment(build_experiment_report(data, "demo@1.0.0"))

    assert "Configuration ranking" in page
    assert 'class="place top">1<' in page
    assert 'class="place">' in page
    assert "knowledge_enabled=False" in page
    assert 'class="bar"' in page
    assert "against the baseline" in page


def test_the_experiment_page_links_each_variant_to_its_own_page(
    database_url: str, tmp_path: Path
) -> None:
    """A variant uid is a link only to a page that exists.

    The Variants table names the recordings, and each uid opens its own page:
    the page the tree writes for that uid, and nothing else.
    """
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"

    page = (root / "experiments" / "demo@1.0.0" / "index.html").read_text(encoding="utf-8")
    for variant_uid in ("v-1", "v-2"):
        # root-addressed, so it resolves from this page two directories deep
        assert (
            f'href="../../experiments/demo@1.0.0/variants/{variant_uid}/index.html"' in page
        ), variant_uid
    for variant_uid in ("v-1", "v-2"):
        assert (
            root / "experiments" / "demo@1.0.0" / "variants" / variant_uid / "index.html"
        ).is_file()


def test_the_variant_page_is_one_recording_not_the_pooled_row(
    database_url: str,
) -> None:
    """The variant page states the recording's own numbers, not the merged ones.

    The ranking row it was pooled into is stated too, on its own, because a
    reader who arrived from a variant uid wants to see where those runs were
    counted.
    """
    store = _seeded(database_url)
    store.record_plan(
        experiment_uid="demo@1.0.0",
        title="demo",
        experiment_type="configuration",
        descriptor_id="demo",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg2",
        variants=[
            {
                "uid": "v-3",
                "index": 2,
                "values": {"knowledge_enabled": False},
                "is_baseline": False,
            },
        ],
        snapshots=[{"kind": "agent", "id": "codex", "version": "1.0.0", "digest": "sha256:agent"}],
    )
    store.record_run(
        _run(
            "run-third",
            started_at="2026-10-31T09:00:00+00:00",
            finished_at="2026-10-31T09:02:00+00:00",
            observations={"total_tokens": 50},
        ),
        experiment_uid="demo@1.0.0",
        variant_uid="v-3",
        task=_task_stub(),
    )

    data = collect_history(store)
    report = build_variant_report(data, "demo@1.0.0", "v-3")
    page = render_variant(report)

    # one run of its own, and its token total is 50, not the pooled 150
    assert report.summary["runs"] == 1
    assert "In the configuration ranking" in page
    assert "The other recordings of this configuration" in page
    assert "v-1" in page
    assert "runs of this recording" in page.lower() or "Runs of this recording" in page


def test_the_run_page_links_to_its_variant(database_url: str, tmp_path: Path) -> None:
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    run = (
        tmp_path / "reports" / "runs" / "run-pass" / "index.html"
    ).read_text(encoding="utf-8")
    assert 'href="../../experiments/demo@1.0.0/variants/v-1/index.html"' in run


def test_the_experiment_page_pools_a_configuration_into_one_row(database_url: str) -> None:
    """Two variant uids with the same values, agent and runtime are one row."""
    store = _seeded(database_url)
    store.record_plan(
        experiment_uid="demo@1.0.0",
        title="demo",
        experiment_type="configuration",
        descriptor_id="demo",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg2",
        variants=[
            {
                "uid": "v-3",
                "index": 2,
                "values": {"knowledge_enabled": False},
                "is_baseline": False,
            },
        ],
        snapshots=[{"kind": "agent", "id": "codex", "version": "1.0.0", "digest": "sha256:agent"}],
    )
    store.record_run(
        _run("run-third", started_at="2026-10-31T09:00:00+00:00",
             finished_at="2026-10-31T09:02:00+00:00",
             observations={"total_tokens": 50}),
        experiment_uid="demo@1.0.0",
        variant_uid="v-3",
        task=_task_stub(),
    )

    data = collect_history(store)
    page = render_experiment(build_experiment_report(data, "demo@1.0.0"))

    # v-1 and v-3 carry the same configuration, so the ranking holds two rows,
    # not three, and the pooled one counts both recordings
    assert "1 recording" in page
    assert "2 recordings" in page
    # the token columns of a ranking are per-run means, not sums
    assert "mean input tokens" in page
    assert "mean generated tokens" in page
    assert "mean total tokens" in page
    assert "mean tool calls" in page
    # the pooled row states its window over both recordings
    assert "2026-10-30 10" in page
    assert "2026-10-31 09" in page


def test_the_dashboard_ranks_one_row_per_configuration(database_url: str) -> None:
    """The front page answers which configuration won, over all its runs."""
    store = _seeded(database_url)
    store.record_plan(
        experiment_uid="demo@2.0.0",
        title="demo again",
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
        _run("run-again", started_at="2026-10-31T09:00:00+00:00",
             finished_at="2026-10-31T09:02:00+00:00",
             observations={"total_tokens": 50}),
        experiment_uid="demo@2.0.0",
        variant_uid="v-1",
        task=_task_stub(),
    )

    data = collect_history(store)
    page = render_index(data)

    ranking = page[page.index("Configuration ranking"):]
    ranking = ranking[: ranking.index("<h2>Verdicts</h2>")]
    # the same configuration in two experiments is one row, not two
    assert ranking.count("knowledge_enabled=False") == 1
    assert ranking.count("knowledge_enabled=True") == 1
    # the first experiment is linked (render_index leaves the root token in
    # place; the tree writer rewrites it) and the rest is counted, as is the
    # number of recordings pooled into the row
    assert '{{root}}experiments/demo@1.0.0/index.html' in ranking
    assert "+1 more" in ranking
    assert "2 recordings" in ranking
    # the pooled row counts both recordings of the baseline configuration
    assert "<td class=\"num\">2</td>" in ranking
    # and the note says what a row is
    assert "one row is one configuration" in ranking


def test_the_index_leads_with_the_ranking_of_every_configuration(
    database_url: str,
) -> None:
    """The first thing a report is asked is "which one won", so it comes first."""
    data = collect_history(_seeded(database_url))

    page = render_index(data)

    assert "Configuration ranking" in page
    assert "knowledge_enabled=False" in page
    assert "knowledge_enabled=True" in page
    # the ranking precedes the verdict table it is easier to read than verdicts
    assert page.index("Configuration ranking") < page.index("<h2>Verdicts</h2>")
    # the note says what a row is: one configuration over all of its recordings
    assert "one row is one configuration" in page
    assert "means per run" in page


def test_a_ranking_of_nothing_says_so_rather_than_ranking_nothing() -> None:
    from akbench.reporting.render import _ranking

    rendered = _ranking([], {})
    assert rendered == '<p class="muted">nothing recorded</p>'
    unscored = _ranking(
        [{"uid": "r", "experiment_uid": "demo@1.0.0", "variant_uid": "v-1"}],
        {"demo@1.0.0": [{"uid": "v-1", "values": {}, "is_baseline": True}]},
    )
    assert "no place can be stated" in unscored


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


# ----------------------------------------------------------- link integrity


def _resolve_links(root: Path) -> list[tuple[str, str]]:
    """Every href in the tree that points at a file that was never written."""
    from urllib.parse import unquote

    broken: list[tuple[str, str]] = []
    for page in sorted(root.rglob("*.html")):
        for href in re.findall(r'href="([^"]+)"', page.read_text(encoding="utf-8")):
            if href.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (page.parent / unquote(href)).resolve().exists():
                broken.append((str(page.relative_to(root)), href))
    return broken


def test_no_link_in_the_tree_points_at_a_page_that_was_not_written(
    database_url: str, tmp_path: Path
) -> None:
    """A dashboard label that reads like a link has to lead somewhere.

    The dashboard links verdicts, categories, difficulties, agents, runtimes,
    plugins and models; each of those needs a page, or the report is a wall of
    dead ends. This walks every written page and resolves every href.
    """
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)

    assert _resolve_links(tmp_path / "reports") == []


def test_the_subject_pages_behind_the_dashboard_labels_exist(
    database_url: str, tmp_path: Path
) -> None:
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    relative = {
        str(path.relative_to(tmp_path / "reports"))
        for path in (tmp_path / "reports").rglob("index.html")
    }

    assert "categories/bug-fix/index.html" in relative
    assert "difficulties/easy/index.html" in relative
    assert "verdicts/passed/index.html" in relative
    assert "verdicts/failed/index.html" in relative
    assert "agents/codex-0.1.0/index.html" in relative
    assert "runs/index.html" in relative


# ---------------------------------------------------------------- run pages


def test_every_run_has_its_own_page_with_its_parameters_and_results(
    database_url: str, tmp_path: Path
) -> None:
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"
    page = (root / "runs" / "run-pass" / "index.html").read_text(encoding="utf-8")

    assert "run-pass" in page
    # where the run belongs, with the configuration it was executed under
    assert "knowledge_enabled=False" in page
    assert "wordcount-001@1.0.0" in page
    # and what came out of it
    assert "passed" in page
    assert "Evaluation" in page


def test_a_run_uid_is_a_link_from_every_table_that_lists_runs(
    database_url: str, tmp_path: Path
) -> None:
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"

    task_page = (root / "tasks" / "wordcount-001@1.0.0" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'href="../../runs/run-pass/index.html"' in task_page
    experiment_page = (root / "experiments" / "demo@1.0.0" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'href="../../runs/run-pass/index.html"' in experiment_page


def test_a_subject_page_lists_the_experiments_of_that_subject(
    database_url: str, tmp_path: Path
) -> None:
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"
    agent_page = (root / "agents" / "codex-0.1.0" / "index.html").read_text(encoding="utf-8")

    assert "Experiments this subject took part in" in agent_page
    assert "demo@1.0.0" in agent_page
    assert "Tasks this subject worked" in agent_page


# -------------------------------------------------------------- sortability


def test_table_headers_are_clickable_and_the_script_ships_with_the_page(
    database_url: str, tmp_path: Path
) -> None:
    """Sorting is the one script a page carries, and only reorders rows.

    A page read with scripting off still shows every row, so the default order
    has to stay in the document; the script must not be an external asset.
    """
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"
    page = (root / "tasks" / "wordcount-001@1.0.0" / "index.html").read_text(encoding="utf-8")

    assert 'class="sortable"' in page
    assert 'aria-sort="none"' in page
    assert "<script>" in page
    assert "<script src=" not in page
    # with scripting off the reader still gets every row, in the order that was
    # written in: sorting is a view over the recorded history, not a change to it
    assert page.index("run-fail") < page.index("run-pass")
    rows = re.findall(r'<a href="[^"]*runs/([^/]+)/index\.html"', page)
    assert rows == ["run-fail", "run-pass"]


def test_runs_are_ordered_by_the_time_they_started() -> None:
    """Start order, with the uid breaking a tie: no clock, no reordering."""
    from akbench.reporting.data import order_by_start

    runs = [
        {"uid": "later", "started_at": "2026-11-01T10:00:00+00:00"},
        {"uid": "earlier", "started_at": "2026-11-01T09:00:00+00:00"},
        {"uid": "no-start"},
        {"uid": "also-earlier", "started_at": "2026-11-01T09:00:00+00:00"},
    ]

    ordered = [run["uid"] for run in order_by_start(runs)]

    assert ordered == ["also-earlier", "earlier", "later", "no-start"]

# ------------------------------------------------------- listing pages link out


def test_the_agent_and_runtime_listings_link_to_their_detail_pages(
    database_url: str, tmp_path: Path
) -> None:
    """A row on an agents or runtimes listing is a dead end without the page.

    The listing and the page it points at sit next to each other in the tree
    (agents/index.html links to agents/<slug>/index.html), so the link is built
    from the same slug that the page is written under.
    """
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"

    agents = (root / "agents" / "index.html").read_text(encoding="utf-8")
    assert 'href="codex-0.1.0/index.html">codex@0.1.0</a>' in agents

    runtimes = (root / "runtimes" / "index.html").read_text(encoding="utf-8")
    assert 'href="llm-router/index.html">llm-router</a>' in runtimes


def test_every_token_table_splits_input_generated_total_and_tool_calls(
    database_url: str, tmp_path: Path
) -> None:
    """A single token column hides what was paid and what was generated.

    Every table that reports tokens carries the four cost columns, and a run
    whose agent reported nothing shows a dash rather than a zero.
    """
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"

    for page in (
        root / "index.html",
        root / "agents" / "codex-0.1.0" / "index.html",
        root / "runs" / "run-pass" / "index.html",
    ):
        text = page.read_text(encoding="utf-8")
        for header in (
            "input tokens",
            "generated tokens",
            "total tokens",
            "tool calls",
        ):
            assert header in text, (page.name, header)


def test_the_sorted_header_remembers_the_direction_it_applied(
    database_url: str, tmp_path: Path
) -> None:
    """A second click on the same header must flip, not repeat, the sort.

    The direction is remembered on the header itself (data-dir), because the
    script that does the sorting has no other memory between clicks.
    """
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    page = (
        (tmp_path / "reports" / "tasks" / "wordcount-001@1.0.0" / "index.html")
        .read_text(encoding="utf-8")
    )

    # the direction a click applied is written back onto the header, and the
    # next click reads it before deciding which way to go: without that mark a
    # second click would sort the same way as the first
    assert 'cells[i].setAttribute("data-dir", ascending ? "asc" : "desc")' in page
    assert 'getAttribute("data-dir") !== "asc"' in page
    # and a page that has never been clicked ships with no direction marked,
    # so the first click is the ascending one
    assert 'data-dir="' not in page

# ------------------------------------------------------------------- layout


def test_a_wide_table_marks_its_own_density(database_url: str, tmp_path: Path) -> None:
    """A run table is wide, and the page has to be wider than it is.

    The density class is chosen from the column count so the stylesheet can
    tighten the type exactly where a row of numbers would else run past the
    edge of the screen.
    """
    data = collect_history(_seeded(database_url))
    write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"

    runs_page = (root / "runs" / "index.html").read_text(encoding="utf-8")
    assert '<table class="dense x-dense">' in runs_page
    verdicts = (root / "verdicts" / "index.html").read_text(encoding="utf-8")
    assert "<table>" in verdicts
    assert "x-dense" not in verdicts


def test_the_page_grows_with_the_window_rather_than_capping_early() -> None:
    """A 78rem column on a 2560px monitor wastes half the glass.

    The page is fluid: it fills the window up to a cap set for ultrawide, with
    the number columns hugging their content so the widest table fits.
    """
    assert "max-width: 78rem" not in STYLE
    assert "--page-max" in STYLE
    assert "width: min(100%, var(--page-max))" in STYLE
    assert "table.dense td.num, table.dense th.num { width: 1%; white-space: nowrap; }" in STYLE


# --------------------------------------------------------- documentation tree


def _mini_docs(root: Path) -> list[Path]:
    """A tiny checkout of documents to publish: two areas, one odd link."""
    (root / "docs").mkdir(parents=True)
    readme = root / "README.md"
    readme.write_text(
        "# Demo project\n\nSome **bold** and `code` and a [link](https://example.test).\n",
        encoding="utf-8",
    )
    cli = root / "docs" / "CLI.md"
    cli.write_text(
        "# CLI\n\n## Commands\n\n| Command | Notes |\n|---|---|\n"
        "| `akbench x` | does x |\n\n"
        "```\nplain code block\n```\n\n",
        encoding="utf-8",
    )
    unsafe = root / "docs" / "Unsafe.md"
    unsafe.write_text(
        "# Unsafe\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n",
        encoding="utf-8",
    )
    return [readme, cli, unsafe]


def test_the_docs_tree_publishes_one_page_per_document(
    database_url: str, tmp_path: Path
) -> None:
    """Every document of the checkout gets a page, and the menu names them all."""
    data = collect_history(_seeded(database_url))
    _mini_docs(tmp_path / "checkout")

    written = write_report_tree(
        tmp_path / "reports", data, docs_root=tmp_path / "checkout"
    )
    root = tmp_path / "reports"
    relative = {str(path.relative_to(root)) for path in written}
    assert "docs/index.html" in relative
    assert "docs/readme/index.html" in relative
    assert "docs/docs-cli/index.html" in relative
    assert "docs/docs-unsafe/index.html" in relative

    index = (root / "docs" / "index.html").read_text(encoding="utf-8")
    assert "Documentation" in index
    # the menu lists the documents of every area, and the dashboard links here
    assert "Demo project" in index
    assert "CLI" in index
    assert "Unsafe" in index
    assert "Handbook" in index and "Project" in index


def test_the_document_page_renders_markdown_and_keeps_anchors(
    database_url: str, tmp_path: Path
) -> None:
    """The page of one document is its source, formatted and linkable."""
    data = collect_history(_seeded(database_url))
    _mini_docs(tmp_path / "checkout")

    write_report_tree(tmp_path / "reports", data, docs_root=tmp_path / "checkout")
    root = tmp_path / "reports"
    cli = (root / "docs" / "docs-cli" / "index.html").read_text(encoding="utf-8")

    assert '<h1 id="cli">CLI</h1>' in cli
    assert '<h2 id="commands">Commands</h2>' in cli
    # the table is a real table, the block is a code block, both in prose
    assert "<table" in cli and "<code>akbench x</code>" in cli
    assert 'class="code-block"' in cli
    # the menu marks the current document and lists its own headings
    assert 'class="current"' in cli
    assert 'href="#commands"' in cli


def test_a_document_page_escapes_its_source(
    database_url: str, tmp_path: Path
) -> None:
    """A document is untrusted input: script stays text, a scheme link stays inert."""
    data = collect_history(_seeded(database_url))
    _mini_docs(tmp_path / "checkout")

    write_report_tree(tmp_path / "reports", data, docs_root=tmp_path / "checkout")
    root = tmp_path / "reports"
    unsafe = (root / "docs" / "docs-unsafe" / "index.html").read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in unsafe
    assert "&lt;script&gt;" in unsafe
    assert 'href="javascript:' not in unsafe


def test_the_docs_index_says_when_no_document_was_found(
    database_url: str, tmp_path: Path
) -> None:
    """A report written away from a checkout says the prose was not found."""
    data = collect_history(_seeded(database_url))

    written = write_report_tree(tmp_path / "reports", data)
    root = tmp_path / "reports"
    index = (root / "docs" / "index.html").read_text(encoding="utf-8")
    assert "no document was found" in index
    # the dashboard still links to the page, and the page is written
    assert "docs/index.html" in {str(path.relative_to(root)) for path in written}
