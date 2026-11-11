"""CLI behaviour of the dataset command group."""

from __future__ import annotations

import json
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
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    import shutil

    shutil.copytree(REPO_ROOT / "datasets", root / "datasets")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(__import__("os").environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root


def _payload(output: str) -> dict:
    return json.loads(output)


def test_help_lists_dataset_commands(project: Path) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dataset" in result.output


def test_dataset_list_json_shape(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["count"] == 85
    assert {task["id"] for task in payload["tasks"]} == {
        "wordcount-001",
        "bookshop-tiers-001",
        "bookshop-stock-002",
        "slugify-001",
        "notes-search-001",
        "notes-sync-001",
        "cadence-catchup-001",
        "cadence-takeover-001",
        "ledgerlite-reconcile-001",
        "ledgerlite-rates-001",
        "stockpile-fefo-001",
        "stockpile-writeoff-001",
        "freight-shop-001",
        "streamforge-windows-001",
        "walqueue-recovery-001",
        "typeweave-inference-001",
        "depweaver-backtracking-001",
        "atlas-drift-001",
        "atlas-drift-002",
        "atlas-drift-003",
        "atlas-drift-004",
        "atlas-lineage-001",
        "atlas-quorum-001",
        "atlas-quorum-002",
        "atlas-quorum-003",
        "atlas-quorum-004",
        "atlas-schema-001",
        "atlas-schema-002",
        "tidewater-election-001",
        "tidewater-election-002",
        "tidewater-election-003",
        "tidewater-snapshot-001",
        "tidewater-snapshot-002",
        "depweaver-lockfile-001",
        "walqueue-compaction-002",
        "timetable-overlap-001",
        "quiz-streak-001",
        "garden-watering-001",
        "playlist-queue-001",
        "cachekit-eviction-001",
        "timetable-slots-001",
        "quiz-ranking-001",
        "garden-plan-001",
        "playlist-mix-001",
        "cachekit-ttl-001",
        "csvkit-quoted-field-001",
        "dates-month-boundary-001",
        "indexer-stale-entry-001",
        "pipeline-stage-order-001",
        "retryq-retry-order-001",
        "syncer-conflict-001",
        "authkit-token-reuse-001",
        "authkit-token-timing-001",
        "configkit-unsafe-load-001",
        "fetcher-open-redirect-001",
        "filebox-path-traversal-001",
        "shopdb-sql-injection-001",
        "billing-split-function-001",
        "forms-extract-validator-001",
        "queuekit-deque-migration-001",
        "reportgen-split-module-001",
        "rules-early-return-001",
        "session-explicit-state-001",
        "cachekit-lru-001",
        "garden-watering-tests-001",
        "playlist-queue-tests-001",
        "quiz-streak-tests-001",
        "timetable-overlap-tests-001",
        "wordcount-top-words-001",
        "review-api-break-001",
        "review-leak-001",
        "review-pr-large-001",
        "review-pr-multi-001",
        "review-pr-small-001",
        "review-race-001",
        "config-cache-001",
        "dedup-linear-001",
        "fib-memo-001",
        "index-lookup-001",
        "inverted-index-001",
        "sorted-search-001",
        "eventbus-decoupling-001",
        "inventory-repository-001",
        "plugcore-registry-001",
        "shopcore-layered-001",
    }
    assert {task["category"] for task in payload["tasks"]} == {
        "bug_fix",
        "new_feature",
        "debugging",
        "security",
        "refactoring",
        "testing",
        "code_review",
        "performance",
        "architecture",
    }
    for task in payload["tasks"]:
        assert task["digest"].startswith("sha256:")


def test_dataset_list_category_filter(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "list", "--category", "bug_fix", "--json"])
    assert _payload(result.output)["count"] == 25
    result = runner.invoke(app, ["dataset", "list", "--category", "new_feature", "--json"])
    assert _payload(result.output)["count"] == 20
    result = runner.invoke(app, ["dataset", "list", "--category", "nope", "--json"])
    assert _payload(result.output)["count"] == 0


def test_dataset_validate_reports_ok(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "validate", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["tasks"] == 85


def test_dataset_validate_fails_on_broken_task(project: Path) -> None:
    hidden = project / "datasets" / "bug_fix" / "wordcount-001" / "hidden_tests"
    for child in hidden.iterdir():
        child.unlink()
    result = runner.invoke(app, ["dataset", "validate", "--json"])
    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["ok"] is False
    # The task order is the directory order, so the broken one is found by name
    # rather than by position in the list.
    broken = [entry for entry in payload["results"] if entry["task"].startswith("wordcount-001")]
    assert broken and any("hidden tests" in issue for issue in broken[0]["issues"])


def test_dataset_validate_verifies_mutation(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "validate", "--verify-mutations", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    checks = {entry["task"]: entry["checks"] for entry in payload["results"]}
    # Every bug-fix task has to arrive at "verified": its hidden tests pass on
    # the pinned base commit and fail once the mutation is applied.
    assert checks["wordcount-001@1.0.0"]["mutation_verified"] == "verified"
    assert checks["bookshop-tiers-001@1.0.0"]["mutation_verified"] == "verified"
    assert checks["bookshop-stock-002@1.0.0"]["mutation_verified"] == "verified"
    assert checks["cadence-takeover-001@1.0.0"]["mutation_verified"] == "verified"
    assert checks["ledgerlite-rates-001@1.0.0"]["mutation_verified"] == "verified"
    assert checks["stockpile-writeoff-001@1.0.0"]["mutation_verified"] == "verified"
    assert checks["walqueue-recovery-001@1.0.0"]["mutation_verified"] == "verified"
    assert checks["depweaver-backtracking-001@1.0.0"]["mutation_verified"] == "verified"
    # The memory suite's bug-fix tasks, over the two seeds it added.
    for task in ("atlas-quorum-001", "atlas-quorum-002", "atlas-quorum-003", "atlas-quorum-004",
                 "tidewater-election-001", "tidewater-election-002", "tidewater-election-003",
                 "walqueue-compaction-002"):
        assert checks[f"{task}@1.0.0"]["mutation_verified"] == "verified", task
    # A new-feature task has no mutation to verify.
    assert checks["slugify-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["notes-search-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["notes-sync-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["cadence-catchup-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["ledgerlite-reconcile-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["stockpile-fefo-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["freight-shop-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["streamforge-windows-001@1.0.0"]["mutation_verified"] == "no_mutation"
    assert checks["typeweave-inference-001@1.0.0"]["mutation_verified"] == "no_mutation"
    for task in ("atlas-schema-001", "atlas-schema-002", "depweaver-lockfile-001",
                 "tidewater-snapshot-001", "tidewater-snapshot-002"):
        assert checks[f"{task}@1.0.0"]["mutation_verified"] == "no_mutation", task


def test_dataset_show_json_shape(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "show", "wordcount-001", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["id"] == "wordcount-001"
    assert payload["repository"]["ref"] == "HEAD"
    assert payload["repository"]["kind"] == "seed"
    assert payload["mutation"]["patch"] == "mutations/mutation-001.patch"


def test_dataset_show_unknown_fails(project: Path) -> None:
    result = runner.invoke(app, ["dataset", "show", "nope", "--json"])
    assert result.exit_code == 1
    assert "unknown task" in result.output


def test_dataset_prepare_creates_and_reports(project: Path) -> None:
    result = runner.invoke(
        app, ["dataset", "prepare", "wordcount-001", "--workspace-id", "cli-demo", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["mutation_applied"] is True
    assert Path(payload["path"]).is_dir()
    assert payload["fingerprint"].startswith("sha256:")
    # clean up so the test leaves no workspace behind
    import shutil

    shutil.rmtree(payload["path"], ignore_errors=True)


def test_dataset_prepare_no_mutation(project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "dataset",
            "prepare",
            "wordcount-001",
            "--workspace-id",
            "cli-base",
            "--no-mutation",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["mutation_applied"] is False
    import shutil

    shutil.rmtree(payload["path"], ignore_errors=True)
