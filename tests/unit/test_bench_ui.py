"""Tests for AK-Bench Web UI and real-time dashboard endpoints."""

from __future__ import annotations

from types import SimpleNamespace

from bench_ui.app import create_app
from starlette.testclient import TestClient

from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import upgrade


def _store(database_url: str) -> HistoryStore:
    upgrade(database_url)
    return HistoryStore(create_db_engine(database_url))


def _task_stub(uid: str = "wordcount-001@1.0.0") -> SimpleNamespace:
    from datetime import datetime

    repository = SimpleNamespace(source="https://example.test/wc.git", ref="abc1234")
    return SimpleNamespace(
        uid=uid,
        digest="sha256:task",
        path=None,
        task=SimpleNamespace(
            id=uid.split("@")[0],
            version="1.0.0",
            category="bug_fix",
            difficulty="easy",
            evaluator="pytest",
            created_at=datetime(2026, 11, 1, 12, 0, 0),
            authors=["Alice"],
            title="Word counting must ignore repeated whitespace",
            description="Runs of whitespace are counted as words.",
            task=SimpleNamespace(repository=repository),
        ),
    )


def _seeded_store(database_url: str) -> HistoryStore:
    store = _store(database_url)
    store.record_plan(
        experiment_uid="test-exp@1.0.0",
        title="Test Matrix Experiment",
        description="Comparing baseline with knowledge arm",
        experiment_type="matrix",
        descriptor_id="test-exp",
        descriptor_version="1.0.0",
        config_hash="sha256:cfg",
        variants=[
            {
                "uid": "v-base",
                "index": 0,
                "values": {"knowledge": False, "model": "base-model"},
                "is_baseline": True,
            },
            {
                "uid": "v-opt",
                "index": 1,
                "values": {"knowledge": True, "model": "opt-model"},
                "is_baseline": False,
            },
        ],
    )
    # Run 1: base pass
    store.record_run(
        {
            "run_uid": "run-001",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "state": "completed",
            "started_at": "2026-11-06T10:00:00+00:00",
            "finished_at": "2026-11-06T10:05:00+00:00",
            "evaluation": {
                "verdict": "passed",
                "score": 1.0,
                "passed": 10,
                "failed": 0,
                "total": 10,
            },
            "observations": {"total_tokens": 5000, "input_tokens": 4000, "output_tokens": 1000},
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-base",
        task=_task_stub(),
    )
    # Run 2: opt partial
    store.record_run(
        {
            "run_uid": "run-002",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "state": "completed",
            "started_at": "2026-11-06T10:10:00+00:00",
            "finished_at": "2026-11-06T10:12:00+00:00",
            "evaluation": {
                "verdict": "partial",
                "score": 0.9,
                "passed": 9,
                "failed": 1,
                "total": 10,
            },
            "observations": {"total_tokens": 2000, "input_tokens": 1600, "output_tokens": 400},
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-opt",
        task=_task_stub(),
    )
    return store


def test_dashboard_endpoint_renders(database_url: str) -> None:
    _seeded_store(database_url)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "Benchmark Dashboard" in response.text
    assert "Configuration Performance" in response.text
    assert "test-exp@1.0.0" in response.text or "run-001" in response.text


def test_runs_page_and_filtering(database_url: str) -> None:
    _seeded_store(database_url)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    # General page
    response = client.get("/runs")
    assert response.status_code == 200
    assert "Runs Explorer" in response.text
    assert "run-001" in response.text
    assert "run-002" in response.text

    # Filter by verdict
    r_passed = client.get("/api/runs?verdict=passed")
    assert r_passed.status_code == 200
    data = r_passed.json()
    assert data["total"] == 1
    assert data["runs"][0]["uid"] == "run-001"

    r_partial = client.get("/api/runs?verdict=partial")
    assert r_partial.status_code == 200
    assert r_partial.json()["total"] == 1
    assert r_partial.json()["runs"][0]["uid"] == "run-002"


def test_comparison_page_and_apis(database_url: str) -> None:
    _seeded_store(database_url)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    # Compare page
    response = client.get("/compare")
    assert response.status_code == 200
    assert "Comparison Studio" in response.text
    assert "Task-by-Task Comparison Matrix" in response.text

    # Compare API
    r_configs = client.get("/api/compare/configurations")
    assert r_configs.status_code == 200
    data = r_configs.json()
    assert len(data["configurations"]) >= 2
    assert len(data["task_matrix"]) == 1

    # Run side-by-side diff
    r_diff = client.get("/compare?run_a=run-001&run_b=run-002")
    assert r_diff.status_code == 200
    assert "Side-by-Side Run Execution Diff" in r_diff.text

    r_diff_api = client.get("/api/compare/runs?run_a=run-001&run_b=run-002")
    assert r_diff_api.status_code == 200
    diff_data = r_diff_api.json()
    assert diff_data["deltas"]["score_diff"] == -0.1
    assert diff_data["deltas"]["time_ratio"] == 0.4
    assert diff_data["deltas"]["token_ratio"] == 0.4


def test_experiments_and_tasks_pages(database_url: str) -> None:
    _seeded_store(database_url)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    # Experiments
    r_exp_list = client.get("/experiments")
    assert r_exp_list.status_code == 200
    assert "Test Matrix Experiment" in r_exp_list.text

    r_exp_detail = client.get("/experiments/test-exp@1.0.0")
    assert r_exp_detail.status_code == 200
    assert "Test Matrix Experiment" in r_exp_detail.text

    # Tasks
    r_tasks_list = client.get("/tasks")
    assert r_tasks_list.status_code == 200
    assert "wordcount-001@1.0.0" in r_tasks_list.text

    r_task_detail = client.get("/tasks/wordcount-001@1.0.0")
    assert r_task_detail.status_code == 200
    assert "wordcount-001@1.0.0" in r_task_detail.text


def test_the_footer_links_the_projects_on_every_page(database_url: str) -> None:
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    for page in ("/", "/runs", "/analytics", "/experiments", "/tasks"):
        body = client.get(page).text
        assert "AK-Bench" in body
        assert 'href="https://radlab.dev"' in body, page
        assert 'href="https://llm-router.cloud/"' in body, page


def test_the_task_detail_shows_the_recorded_definition(database_url: str) -> None:
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/tasks/wordcount-001@1.0.0").text
    # The task's own prose, recorded with the run
    assert "Task Definition" in body
    assert "recorded with the run" in body
    assert "Word counting must ignore repeated whitespace" in body
    assert "Runs of whitespace are counted as words." in body
    # The identity that was already recorded
    assert "pytest" in body
    assert "Alice" in body


def test_the_task_detail_reads_the_dataset_when_not_recorded(database_url: str) -> None:
    """A task recorded before its prose was stored still gets a definition.

    The dataset on disk is the fallback source: its one-line description
    reaches the page, and the page says it came from the dataset.
    """
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/tasks/wordcount-001@1.0.0").text
    assert "Task Definition" in body
    # The recorded columns win where they exist
    assert "Runs of whitespace are counted as words." in body
    # The dataset fills in what was never recorded: constraints, the scope of
    # work, the repository and the raw descriptor
    assert "do not change the public API of the wordcount package" in body
    assert "count_words" in body
    assert "datasets/_sources/wordcount" in body
    assert "task.yaml" in body


def test_the_tasks_list_carries_the_task_prose(database_url: str) -> None:
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/tasks").text
    assert "Word counting must ignore repeated whitespace" in body
    assert "Runs of whitespace are counted as words." in body
    assert "Alice" in body


def test_analytics_page_and_data_api(database_url: str) -> None:
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    page = client.get("/analytics")
    assert page.status_code == 200
    assert "Analytics Explorer" in page.text
    assert "/static/js/analytics.js" in page.text

    data = client.get("/api/analytics/data").json()
    assert {r["uid"] for r in data["rows"]} >= {"run-001", "run-002"}
    row = next(r for r in data["rows"] if r["uid"] == "run-001")
    assert row["verdict"] == "passed"
    assert isinstance(row["params"], dict)
    assert isinstance(data["param_keys"], list)


def test_single_run_api(database_url: str) -> None:
    _seeded_store(database_url)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    r = client.get("/api/runs/run-001")
    assert r.status_code == 200
    data = r.json()
    assert data["run"]["uid"] == "run-001"
    assert data["score"] == 1.0
    assert data["verdict"] == "passed"
    assert data["duration_seconds"] == 300.0


def test_overview_api(database_url: str) -> None:
    _seeded_store(database_url)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    r = client.get("/api/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["runs"] == 2
    assert data["summary"]["evaluated"] == 2
    assert data["summary"]["passed"] == 1
    assert data["summary"]["success_rate"] == 0.5
    assert data["summary"]["mean_score"] == 0.95


# ------------------------------------------------------------------ connection
# The dashboard reads the database the same way the CLI does, so a `.env` that
# configures PostgreSQL also configures the UI. Where the database lives is not
# shown: a status is what a reader can act on, and an address is a credential
# in all but name.


def _project_without_env_overrides(monkeypatch, tmp_path):
    import os

    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    for name in list(os.environ):
        if name.startswith("AKBENCH"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AKBENCH_HOME", str(project))
    return project


def test_the_ui_reads_its_database_from_the_env_file(monkeypatch, tmp_path) -> None:
    from bench_ui.service import BenchDataService

    project = _project_without_env_overrides(monkeypatch, tmp_path)
    (project / ".env").write_text(
        "AKBENCH_PG_HOST=db.internal\n"
        "AKBENCH_PG_PORT=6543\n"
        "AKBENCH_PG_USER=akbench\n"
        "AKBENCH_PG_PASSWORD=***\n"
        "AKBENCH_PG_DB=akbench\n"
        "AKBENCH_DB_BACKEND=postgres\n"
        "AKBENCH__DATABASE__POSTGRES__NAMESPACE=knowledge_replay\n",
        encoding="utf-8",
    )

    service = BenchDataService(project_root=project)
    info = service.connectivity()
    assert info["backend"] == "postgres"
    assert info["namespace"] == "knowledge_replay"
    assert info["reachable"] is False  # db.internal does not exist, and is reported as such
    assert info["error"]


def test_the_address_of_the_database_never_reaches_the_pages(monkeypatch, tmp_path) -> None:
    from bench_ui.app import create_app

    app = create_app(database_url="postgresql+psycopg://akbench:***@127.0.0.1:1/none")
    client = TestClient(app)

    page = client.get("/")
    assert page.status_code == 200
    assert "secret" not in page.text
    assert "postgresql+psycopg" not in page.text
    assert "DB OFFLINE" in page.text
    assert "database_url" not in client.get("/api/database").json()


def test_a_live_database_shows_a_status(monkeypatch, tmp_path, database_url: str) -> None:
    from bench_ui.app import create_app

    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    page = client.get("/")
    assert "LIVE DB" in page.text
    assert "sqlite:///" not in page.text
    assert client.get("/api/database").json()["reachable"] is True


# --------------------------------------------------------------------- loader
def test_every_page_carries_the_page_load_indicator(database_url: str) -> None:
    """One markup in the base template: the ramp belongs to the shell, not a page."""
    from bench_ui.app import create_app

    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))
    for page in ("/", "/runs", "/analytics", "/compare", "/experiments", "/tasks"):
        body = client.get(page).text
        assert 'id="pageLoader"' in body, page
        assert 'id="pageLoaderBar"' in body, page
        assert "initPageLoader" in client.get("/static/js/app.js").text
