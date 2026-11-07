"""Tests for AK-Bench Web UI and real-time dashboard endpoints."""

from __future__ import annotations

from types import SimpleNamespace

from bench_ui.app import create_app
from starlette.testclient import TestClient

from bench_ui.service import BenchDataService

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
            "runtime_id": "llm-router-ak-bench",
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
            "runtime_id": "shared-runtime",
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


def _record_junit_artifact(store, run_uid: str, path) -> None:
    """Attach a JUnit report to a run, the way a real evaluator leaves it."""
    store.register_artifacts(run_uid, [path])


def test_dashboard_endpoint_renders(database_url: str) -> None:
    _seeded_store(database_url)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "Benchmark Dashboard" in response.text
    assert "Models: Success Rate" in response.text
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


def _components(store: HistoryStore) -> None:
    """An agent, a runtime and an experiment file, as a real run would store them."""
    store.record_plan(
        experiment_uid="test-exp@1.0.0",
        experiment_yaml=(
            'id: test-exp\nversion: "1.0.0"\n'
            "title: Test Matrix Experiment\n"
            "description: Comparing baseline with knowledge arm\n"
            "experiment:\n  type: configuration\n"
            "  agent: {id: codex, version: '1.0.0'}\n"
            "  execution: {mode: router, runtime: {id: llm-router-ak-bench, version: '1.0.0'}}\n"
            "  execution_policy: {repetitions: 2, concurrency: 1, timeout_seconds: 600}\n"
            "  metrics: [task_success_rate, total_tokens]\n"
        ),
    )
    store.record_run(
        {
            "run_uid": "run-comp",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "runtime_id": "llm-router-ak-bench",
            "state": "completed",
            "evaluation": {"verdict": "passed", "score": 1.0, "passed": 1, "failed": 0, "total": 1},
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-base",
        task=_task_stub(),
        agent_descriptor={
            "id": "codex",
            "version": "1.0.0",
            "title": "Codex CLI",
            "description": "Codex driven non-interactively.",
            "descriptor_yaml": (
                "id: codex\nversion: \"1.0.0\"\ntitle: Codex CLI\n"
                "agent:\n  adapter: codex_cli\n  execution_type: process\n"
                "  capabilities: {token_usage: verified, cost_usage: unsupported}\n"
                "  configuration_schema:\n    model: {type: string, controllable: true}\n"
                "  notes: isolation recipe verified in phase 0\n"
            ),
        },
        runtime_descriptor={
            "id": "llm-router-ak-bench",
            "version": "1.0.0",
            "title": "LLM Router (managed instance)",
            "descriptor_yaml": (
                "id: llm-router-ak-bench\nversion: \"1.0.0\"\n"
                "runtime:\n  adapter: llm_router\n"
                "  execution_modes: [router, runtime, direct]\n"
                "  supported_lifecycles: [managed]\n"
                "  base_url: http://127.0.0.1:8085\n"
                "  managed:\n    factor_env: {knowledge_enabled: LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED}\n"
            ),
        },
    )
    # A second recorded version of the same agent: the catalog must carry both,
    # and the runs filter must be able to name each of them.
    store.record_run(
        {
            "run_uid": "run-comp-b",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "2.0",
            "runtime_id": "llm-router-ak-bench",
            "state": "completed",
            "evaluation": {"verdict": "failed", "score": 0.0, "passed": 0, "failed": 1, "total": 1},
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-opt",
        task=_task_stub(),
        agent_descriptor={
            "id": "codex",
            "version": "2.0",
            "title": "Codex CLI",
            "description": "A newer Codex, recorded at its own version.",
            "descriptor_yaml": (
                "id: codex\nversion: \"2.0\"\ntitle: Codex CLI\n"
                "agent:\n  adapter: codex_cli\n  execution_type: process\n"
                "  capabilities: {token_usage: verified, cost_usage: partial}\n"
            ),
        },
    )


def test_the_experiment_page_shows_its_own_file(database_url: str) -> None:
    _seeded_store(database_url)
    _components(_store(database_url))
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/experiments/test-exp@1.0.0").text
    assert "Experiment Definition" in body
    assert "recorded with the plan" in body
    assert "Comparing baseline with knowledge arm" in body
    assert "llm-router-ak-bench" in body
    assert "task_success_rate" in body
    assert "Experiment file" in body


def test_agent_and_runtime_pages_show_their_descriptors(database_url: str) -> None:
    _seeded_store(database_url)
    _components(_store(database_url))
    client = TestClient(create_app(database_url=database_url))

    listed = client.get("/agents").text
    assert "codex" in listed and "Codex CLI" in listed
    runtime_list = client.get("/runtimes").text
    assert "llm-router-ak-bench" in runtime_list

    agent = client.get("/agents/codex").text
    assert "Codex CLI" in agent
    assert "codex_cli" in agent
    assert "token_usage" in agent and "verified" in agent
    assert "id: codex" in agent

    runtime = client.get("/runtimes/llm-router-ak-bench").text
    assert "LLM Router (managed instance)" in runtime
    assert "http://127.0.0.1:8085" in runtime
    assert "LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED" in runtime

    assert client.get("/agents/nope").status_code == 404
    assert client.get("/runtimes/nope").status_code == 404


def test_runs_can_be_filtered_by_agent_and_runtime(database_url: str) -> None:
    _seeded_store(database_url)
    _components(_store(database_url))
    client = TestClient(create_app(database_url=database_url))

    by_agent = client.get("/api/runs?agent=codex%401.0").json()
    assert "run-comp" in [run["uid"] for run in by_agent["runs"]]
    # a version the history never used matches nothing: the catalog and the
    # filter agree on what was actually recorded
    assert client.get("/api/runs?agent=codex%409.9").json()["runs"] == []

    api = client.get("/api/runs?runtime=llm-router-ak-bench").json()
    assert "run-comp" in [run["uid"] for run in api["runs"]]
    assert all(run["runtime_id"] == "llm-router-ak-bench" for run in api["runs"])

    assert client.get("/api/runs?runtime=some-other-runtime").json()["runs"] == []


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


def test_every_table_header_with_data_sortable_is_wired(database_url: str) -> None:
    """A header that promises sorting must carry the marker the JS looks for."""
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    for page in ("/", "/runs", "/tasks", "/experiments"):
        body = client.get(page).text
        assert 'data-sortable' in body, page
        assert "initSortableTables" in body or "/static/js/app.js" in body


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

    # A URL nobody can actually connect to: the page must say it is offline
    # and must never echo the address or the password.
    app = create_app(database_url="postgresql+psycopg://akbench:***@127.0.0.1:1/none", project_root=tmp_path)
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
def test_the_catalog_pages_are_reachable_from_the_navigation(database_url: str) -> None:
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/").text
    for href in ("/tasks", "/agents", "/runtimes", "/experiments", "/runs", "/analytics"):
        assert f'href="{href}"' in body, href


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


def _task_with_files(store: HistoryStore, root):
    """Record a task whose code — repository, tests, mutation — is on disk."""
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
    (task_dir / "mutations" / "mutation-001.patch").write_text("--- a\n+++ b\n", encoding="utf-8")
    (task_dir / "description.md").write_text("# Word counting\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        'schema_version: "1.0"\nid: wordcount-001\nversion: "1.0.0"\n'
        "task:\n"
        "  category: bug_fix\n"
        "  difficulty: easy\n"
        "  repository:\n"
        "    source: _sources/wordcount\n"
        "    ref: HEAD\n"
        "  mutation:\n"
        "    patch: mutations/mutation-001.patch\n"
        '    version: "1.0.0"\n'
        "  evaluator: pytest_evaluator\n"
        "  hidden_tests: hidden_tests\n"
        "  public_tests: public_tests\n",
        encoding="utf-8",
    )
    loaded = load_task(task_dir)
    store.record_run(
        {
            "run_uid": "run-code",
            "task_uid": loaded.uid,
            "agent_id": "codex",
            "state": "completed",
            "started_at": "2026-11-06T10:00:00+00:00",
        },
        task=loaded,
    )
    return loaded


def test_the_task_detail_shows_its_code_as_a_tree(database_url: str, tmp_path) -> None:
    """The files recorded with a task are listed, grouped by kind."""
    store = _seeded_store(database_url)
    _task_with_files(store, tmp_path)
    client = TestClient(create_app(database_url=database_url))

    response = client.get("/tasks/wordcount-001@1.0.0")

    assert response.status_code == 200
    body = response.text
    assert "Task Code" in body
    for kind in ("repository", "public_tests", "hidden_tests", "mutation"):
        assert kind in body
    assert "__init__.py" in body
    assert "test_hidden.py" in body


def test_the_task_file_api_returns_one_file(database_url: str, tmp_path) -> None:
    store = _seeded_store(database_url)
    _task_with_files(store, tmp_path)
    client = TestClient(create_app(database_url=database_url))

    response = client.get("/api/tasks/wordcount-001@1.0.0/files/src/wordcount/__init__.py")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "repository"
    assert payload["content"].startswith("def count_words(text):")


def test_the_task_files_api_lists_paths_without_content(database_url: str, tmp_path) -> None:
    """A tree is a list of names; the text arrives when a file is opened."""
    store = _seeded_store(database_url)
    _task_with_files(store, tmp_path)
    app = create_app(database_url=database_url)
    client = TestClient(app)

    response = client.get("/api/tasks/wordcount-001@1.0.0/files")

    assert response.status_code == 200
    groups = response.json()
    kinds = [group["kind"] for group in groups]
    assert kinds == ["repository", "public_tests", "hidden_tests", "mutation"]
    repository = groups[0]["tree"]["children"]
    names = {node["name"] for node in repository}
    assert {"src", "README.md"} <= names


def test_an_unrecorded_file_is_not_invented(database_url: str, tmp_path) -> None:
    store = _seeded_store(database_url)
    _task_with_files(store, tmp_path)
    client = TestClient(create_app(database_url=database_url))

    missing = client.get("/api/tasks/wordcount-001@1.0.0/files/src/nope.py")
    unknown_task = client.get("/api/tasks/nope@1.0.0/files")

    assert missing.status_code == 404
    assert unknown_task.status_code == 404


def test_the_agents_catalog_lists_each_recorded_version_with_its_runs(
    database_url: str
) -> None:
    """An agent at the version a run recorded is a row of its own.

    A run named codex at 2.0 is not the same fact as codex at 1.0.0: the
    catalog lists both, each linking to the runs that actually used it.
    """
    _seeded_store(database_url)
    _components(_store(database_url))
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/agents").text
    # the version column is the version the runs recorded, and every row links
    # to the runs filtered to its own id@version
    assert 'href="/runs?agent=codex%401.0"' in body
    assert 'href="/runs?agent=codex%402.0"' in body

    v2 = client.get("/api/runs?agent=codex%402.0").json()
    assert [run["uid"] for run in v2["runs"]] == ["run-comp-b"]
    v1 = client.get("/api/runs?agent=codex%401.0").json()
    assert "run-comp" in [run["uid"] for run in v1["runs"]]
    assert "run-comp-b" not in [run["uid"] for run in v1["runs"]]


def test_the_runs_page_carries_the_runtime_filter(database_url: str) -> None:
    """The runtime dropdown lists what the history actually used, and filters."""
    _seeded_store(database_url)
    _components(_store(database_url))
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/runs").text
    assert 'select id="filterRuntime"' in body
    assert "llm-router-ak-bench" in body and "shared-runtime" in body

    managed = client.get("/api/runs?runtime=llm-router-ak-bench").json()
    assert "run-001" in [run["uid"] for run in managed["runs"]]
    assert "run-002" not in [run["uid"] for run in managed["runs"]]
    shared = client.get("/api/runs?runtime=shared-runtime").json()
    assert [run["uid"] for run in shared["runs"]] == ["run-002"]


def test_the_run_diff_opens_on_two_runs_chosen_from_lists(database_url: str) -> None:
    """The run diff is a view, and it opens with two runs already selected.

    Two text inputs asked the reader to know two uids by heart; two lists over
    the same runs name each one by its task and outcome instead.
    """
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    runs_view = client.get("/compare?view=runs")
    assert runs_view.status_code == 200
    body = runs_view.text
    assert 'name="run_a"' in body and 'name="run_b"' in body
    # the labels say what a run was, not only what it is called
    assert "run-002" in body and "run-001" in body
    assert "Score Difference" in body

    # the configurations view stays the default and carries no picker
    default = client.get("/compare").text
    assert 'name="run_a"' not in default
    assert "Task-by-Task Comparison Matrix" in default

    # an explicit pair wins over the default one
    chosen = client.get("/compare?run_a=run-001&run_b=run-002").text
    assert 'value="run-001" selected' in chosen
    assert 'value="run-002" selected' in chosen


def test_the_runs_page_limits_the_comparison_to_two_runs(database_url: str) -> None:
    """Two checks are the whole budget, and the page says so while choosing.

    The comparison takes exactly two runs; the explorer therefore announces
    the budget and hands the running out of it to the script, instead of
    letting a third checkbox appear to work.
    """
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/runs").text
    assert 'id="runsSelectionHint"' in body
    assert "select 2 runs" in body

    script = client.get("/static/js/app.js").text
    assert "COMPARISON_SIZE" in script
    assert "applyRunSelectionLimits" in script


def test_the_dashboard_charts_compare_models_not_metrics(database_url: str) -> None:
    """The charts ask how the models differ, not how one differs from itself.

    Two runs of the same model under different configurations used to be two
    bars of the same metric; grouping by model makes the comparison a reader
    can act on: same set of tasks, different models, per-model success rate,
    score, duration and tokens.
    """
    _seeded_store(database_url)
    store = _store(database_url)
    # two runs, same task, two different models
    store.record_run(
        {
            "run_uid": "run-model-a",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "requested_model": "model-a",
            "observed_model": "model-a",
            "state": "completed",
            "evaluation": {"verdict": "passed", "score": 1.0, "passed": 5, "failed": 0, "total": 5},
            "observations": {"total_tokens": 1000, "input_tokens": 800, "output_tokens": 200},
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-base",
        task=_task_stub(),
    )
    store.record_run(
        {
            "run_uid": "run-model-b",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "requested_model": "model-b",
            "observed_model": "model-b",
            "state": "completed",
            "evaluation": {"verdict": "failed", "score": 0.0, "passed": 1, "failed": 4, "total": 5},
            "observations": {"total_tokens": 2000, "input_tokens": 1500, "output_tokens": 500},
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-opt",
        task=_task_stub(),
    )

    client = TestClient(create_app(database_url=database_url))
    body = client.get("/").text

    # one bar per model, the same metric in both charts
    assert "chartModelPerformance" in body and "chartModelCost" in body
    assert "model-a" in body and "model-b" in body
    import json, re
    match = re.search(r"const models = (\[.*?\]);", body, re.S)
    models = json.loads(match.group(1))
    by_model = {row["model"]: row for row in models}
    assert by_model["model-a"]["success_rate"] == 1.0
    assert by_model["model-b"]["success_rate"] == 0.0
    assert by_model["model-a"]["mean_total_tokens"] == 1000


def test_the_run_tables_carry_a_tool_calls_column(database_url: str) -> None:
    """A run's effort is not only its tokens: the tables must show the calls.

    Tool calls were recorded and summed but never printed, so a reader could
    not see that one configuration did the same work in a tenth of the calls.
    Every table that lists runs or configurations carries the column, with the
    raw number beside it for sorting.
    """
    store = _seeded_store(database_url)
    store.record_run(
        {
            "run_uid": "run-tools",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "runtime_id": "llm-router-ak-bench",
            "state": "completed",
            "started_at": "2026-11-06T11:00:00+00:00",
            "finished_at": "2026-11-06T11:01:00+00:00",
            "evaluation": {
                "verdict": "passed",
                "score": 1.0,
                "passed": 10,
                "failed": 0,
                "total": 10,
            },
            "observations": {"total_tokens": 900, "tool_call_count": 17},
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-base",
        task=_task_stub(),
    )
    client = TestClient(create_app(database_url=database_url))

    # the number reaches the API the explorer paints from
    api_runs = client.get("/api/runs").json()["runs"]
    by_uid = {run["uid"]: run for run in api_runs}
    assert by_uid["run-tools"]["tool_call_count"] == 17

    for path in ("/runs", "/", "/tasks", "/experiments", "/experiments/test-exp@1.0.0", "/tasks/wordcount-001@1.0.0"):
        body = client.get(path).text
        assert "Tool Calls" in body, path

    # a run that stated its calls shows them, with a sort key beside the text
    runs_body = client.get("/runs").text
    assert 'data-sort-value="17"' in runs_body

    detail = client.get("/experiments/test-exp@1.0.0").text
    assert "Tool Calls" in detail


def test_a_task_page_offers_its_code_as_one_archive(database_url: str, tmp_path) -> None:
    """The whole recorded code of a task, in a file named after the task.

    A reader who wants to work the task themselves wants the files, not a page
    of them, and wants the download to say which task and which version it is.
    """
    import io
    import zipfile

    store = _seeded_store(database_url)
    _task_with_files(store, tmp_path)
    client = TestClient(create_app(database_url=database_url))

    response = client.get("/api/tasks/wordcount-001@1.0.0/download.zip")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert 'filename="wordcount-001__1.0.0.zip"' in response.headers["content-disposition"]

    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert "repository/src/wordcount/__init__.py" in names
    assert "hidden_tests/hidden_tests/test_hidden.py" in names
    assert "public_tests/public_tests/test_public.py" in names
    assert any(name.endswith("mutation-001.patch") for name in names)

    # the page offers it, and the offer does not fold the panel when clicked
    body = client.get("/tasks/wordcount-001@1.0.0").text
    assert "/api/tasks/wordcount-001@1.0.0/download.zip" in body
    assert "event.stopPropagation()" in body

    missing = client.get("/api/tasks/never-recorded@9.9.9/download.zip")
    assert missing.status_code == 404


def test_the_task_page_folds_its_long_prose_and_its_code(database_url: str, tmp_path) -> None:
    """Description and code open and close: neither is the page's first point."""
    store = _seeded_store(database_url)
    _task_with_files(store, tmp_path)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/tasks/wordcount-001@1.0.0").text

    assert '<details class="panel raw-descriptor">' in body
    # the description panel is a <details> whose summary names the file
    assert "<summary" in body
    description_header = body.split("description.md")[0]
    assert description_header.count("<details") >= 1


def test_the_task_page_charts_score_per_configuration(database_url: str) -> None:
    """One line per configuration: the same task under different factors."""
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/tasks/wordcount-001@1.0.0").text

    assert 'id="chartTaskScore"' in body
    assert "Score by Configuration" in body
    # the series are built from the runs of this task, keyed by configuration
    assert "byConfig" in body
    assert "knowledge=False" in body or "model=base-model" in body


def test_a_formatted_cell_sorts_by_the_number_it_shows(database_url: str) -> None:
    """A percentage inside a bar sorted on nothing: the text it shows is the key.

    Whitespace between the cell and the value inside it is not a value, and a
    cell whose own text is only whitespace used to sort on that — a column of
    success rates that refused to move.
    """
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    script = client.get("/static/js/app.js").text
    assert "text.trim() || (cell.textContent || '').trim()" in script

    # the success rate and mean score columns carry their raw number beside the
    # bar, and the against-baseline column carries the difference it describes
    body = client.get("/").text
    assert 'data-sort-value="1.0"' in body
    assert 'data-sort-value="0.9"' in body
    assert 'data-sort-value="-1.0"' in body


def test_the_analytics_charts_spin_until_their_data_arrives() -> None:
    """An empty chart is indistinguishable from a broken one, so it spins."""
    client = TestClient(create_app(database_url="sqlite:///:memory:"))

    body = client.get("/analytics").text
    assert "analytics.js" in body

    script = client.get("/static/js/analytics.js").text
    assert "armSpinners" in script and "clearSpinners" in script

    css = client.get("/static/css/style.css").text
    assert "an-chart-loading" in css and "an-spin" in css


def test_the_dashboard_opens_with_the_overall_ledger(database_url: str) -> None:
    """How much benchmark there is, before the reader asks the charts a question."""
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/").text

    for label in (
        "experiments", "runs", "evaluated", "success rate", "tasks",
        "total time", "mean time", "input tokens", "generated tokens",
        "tokens", "tool calls", "cost",
    ):
        assert label in body, label

    stats = client.get("/api/tasks")  # the ledger is served with the dashboard
    assert stats.status_code == 200

    service = BenchDataService(database_url=database_url)
    ledger = {row["label"]: row["value"] for row in service.get_dashboard_stats()}
    assert ledger["runs"] == "2"
    assert ledger["experiments"] == "1"
    assert ledger["tasks"] == "1"
    assert ledger["cost"] == "not recorded"
    # two runs of five and two minutes: the total is their sum, the mean their mean
    assert ledger["total time"] == "7 m 0 s"
    assert ledger["mean time"] == "3 m 30 s"
    assert ledger["tokens"] == "7,000"


def test_the_run_inspector_names_its_tests(database_url: str, tmp_path) -> None:
    """Which test failed, not only how many did.

    The evaluator's JUnit report is read from the run's artifacts, so a run
    that recorded per-test results shows them and a run that did not says so
    rather than pretending an empty list is a clean sheet.
    """
    store = _seeded_store(database_url)
    run = store.run("run-001")
    directory = tmp_path / "evaluation"
    directory.mkdir()
    (directory / "junit.xml").write_text(
        '<?xml version="1.0" ?><testsuites><testsuite name="pytest" tests="3"'
        ' failures="1" errors="0" skipped="1">'
        '<testcase classname="tests.test_wc" name="test_spaces" time="0.004" />'
        '<testcase classname="tests.test_wc" name="test_tabs" time="0.001">'
        '<failure message="assert 1 == 2">assert 1 == 2</failure></testcase>'
        '<testcase classname="tests.test_wc" name="test_newlines" time="0.000">'
        '<skipped message="needs a fixture" /></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    _record_junit_artifact(store, run["uid"], directory / "junit.xml")

    client = TestClient(create_app(database_url=database_url))
    detail = client.get("/api/runs/run-001").json()
    tests = detail["tests"]
    assert [test["status"] for test in tests] == ["passed", "failed", "skipped"]
    assert tests[1]["name"] == "test_tabs"
    assert "assert 1 == 2" in tests[1]["detail"]

    # a run whose evaluator wrote no report says so
    other = client.get("/api/runs/run-002").json()
    assert other["tests"] == []

    script = client.get("/static/js/app.js").text
    assert "renderRunTests" in script


def test_the_descriptors_are_coloured_copied_and_attributed(database_url: str, tmp_path) -> None:
    """A YAML file is read by its keys, and a value on screen should be copyable.

    The leaderboard also names the instrument behind a row: two rows may share
    a configuration because they were measured under different agent versions,
    and showing that is honest while leaving it hidden is confusing.
    """
    store = _seeded_store(database_url)
    _task_with_files(store, tmp_path)
    client = TestClient(create_app(database_url=database_url))

    task_body = client.get("/tasks/wordcount-001@1.0.0").text
    assert "yaml-block" in task_body
    assert task_body.count("data-copy-target") >= 3

    script = client.get("/static/js/app.js").text
    assert "initYamlHighlighting" in script and "highlightYaml" in script
    assert "initCopyButtons" in script

    dashboard = client.get("/").text
    assert "codex@1.0" in dashboard  # the agent a row was measured under


def test_run_tables_carry_the_repetition_number(database_url: str) -> None:
    """Which repetition a run was, beside the run itself."""
    store = _seeded_store(database_url)
    store.record_run(
        {
            "run_uid": "run-repeat-2",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "state": "completed",
            "started_at": "2026-11-06T12:00:00+00:00",
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-base",
        repetition=2,
        task=_task_stub(),
    )
    client = TestClient(create_app(database_url=database_url))

    api_runs = client.get("/api/runs").json()["runs"]
    by_uid = {run["uid"]: run for run in api_runs}
    assert by_uid["run-repeat-2"]["repetition"] == 2

    for path in ("/runs", "/", "/experiments/test-exp@1.0.0", "/tasks/wordcount-001@1.0.0"):
        assert ">Rep</th>" in client.get(path).text, path
    assert ">Rep</th>" in client.get("/runs").text
    assert 'data-sort-value="2"' in client.get("/runs").text


def test_each_run_row_carries_its_own_score_history(database_url: str) -> None:
    """A score is only readable against the runs it came out of.

    A row now carries the history of its own task under its own configuration,
    in the order the runs started, plus the mean the task's declared baseline
    reached — so an outlier run is visible without opening it.
    """
    store = _seeded_store(database_url)
    for index, (uid, score) in enumerate(
        [("run-late-1", 0.4), ("run-late-2", 1.0)], start=1
    ):
        store.record_run(
            {
                "run_uid": uid,
                "task_uid": "wordcount-001@1.0.0",
                "agent_id": "codex",
                "agent_version": "1.0",
                "state": "completed",
                "started_at": f"2026-11-06T1{index}:00:00+00:00",
                "evaluation": {
                    "verdict": "partial" if score < 1 else "passed",
                    "score": score,
                    "passed": int(score * 10),
                    "failed": 10 - int(score * 10),
                    "total": 10,
                },
            },
            experiment_uid="test-exp@1.0.0",
            variant_uid="v-opt",
            task=_task_stub(),
        )
    client = TestClient(create_app(database_url=database_url))

    runs = {run["uid"]: run for run in client.get("/api/runs").json()["runs"]}
    late = runs["run-late-2"]
    # the v-opt series in the order it ran: the seeded partial, then 0.4, then 1.0
    assert late["trend_points"] == [0.9, 0.4, 1.0]
    assert late["trend_index"] == 2
    assert late["trend_csv"] == "0.9000,0.4000,1.0000"
    # the baseline of this task is v-base, which scored 1.0
    assert late["baseline_score"] == 1.0

    body = client.get("/runs").text
    assert ">Trend</th>" in body
    assert 'data-points="0.9000,0.4000,1.0000"' in body
    assert 'data-baseline="1.0"' in body

    script = client.get("/static/js/app.js").text
    assert "initSparklines" in script and "renderSparkline" in script


def test_the_run_inspector_splits_what_a_run_paid_in(database_url: str) -> None:
    """One number is not a cost: the split across input, cache, output, reasoning is.

    The inspector's token card breaks a run's tokens into the four things they
    were spent on and leads with the cache hit ratio, because that is the
    number that says whether the input was paid for twice.
    """
    store = _seeded_store(database_url)
    store.record_run(
        {
            "run_uid": "run-tokens",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "state": "completed",
            "started_at": "2026-11-06T14:00:00+00:00",
            "observations": {
                "input_tokens": 1000,
                "cached_input_tokens": 250,
                "output_tokens": 200,
                "reasoning_output_tokens": 50,
                "total_tokens": 1200,
            },
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-base",
        task=_task_stub(),
    )
    client = TestClient(create_app(database_url=database_url))

    detail = client.get("/api/runs/run-tokens").json()
    obs = detail["run"]["observations"]
    assert obs["cached_input_tokens"] == 250
    assert obs["reasoning_output_tokens"] == 50

    script = client.get("/static/js/app.js").text
    assert "renderTokenBreakdown" in script
    # the headline the card leads with, and all four parts of the split
    for token in ("cache hit", "'input'", "'cached'", "'output'", "'reasoning'"):
        assert token in script

    css = client.get("/static/css/style.css").text
    assert ".token-bar" in css and ".token-legend" in css


def test_the_experiment_page_scores_tasks_against_configurations(database_url: str) -> None:
    """A configuration is only interesting relative to the task it is applied to.

    The page therefore reads a grid — one cell per task and configuration,
    coloured by the mean score it earned — and a cell with no runs is a
    missing cell, not a zero.
    """
    store = _seeded_store(database_url)
    # a second task, scored under both variants, so a weak cell exists
    from types import SimpleNamespace
    from datetime import datetime

    stub = SimpleNamespace(
        uid="second-001@1.0.0",
        digest="sha256:second",
        path=None,
        task=SimpleNamespace(
            id="second-001", version="1.0.0", category="bug_fix", difficulty="easy",
            evaluator="pytest", created_at=datetime(2026, 11, 1, 12, 0, 0), authors=["Alice"],
            title="Second", description="d", task=SimpleNamespace(repository=SimpleNamespace(source="s", ref="r")),
        ),
    )
    store.record_run(
        {"run_uid": "r-second-base", "task_uid": "second-001@1.0.0", "agent_id": "codex",
         "agent_version": "1.0", "state": "completed", "started_at": "2026-11-06T15:00:00+00:00",
         "evaluation": {"verdict": "passed", "score": 1.0, "passed": 10, "failed": 0, "total": 10}},
        experiment_uid="test-exp@1.0.0", variant_uid="v-base", task=stub,
    )
    store.record_run(
        {"run_uid": "r-second-opt", "task_uid": "second-001@1.0.0", "agent_id": "codex",
         "agent_version": "1.0", "state": "completed", "started_at": "2026-11-06T15:10:00+00:00",
         "evaluation": {"verdict": "failed", "score": 0.2, "passed": 2, "failed": 8, "total": 10}},
        experiment_uid="test-exp@1.0.0", variant_uid="v-opt", task=stub,
    )
    client = TestClient(create_app(database_url=database_url))
    service = BenchDataService(database_url=database_url)
    matrix = service.get_experiment_detail("test-exp@1.0.0")["score_matrix"]
    by_task = {row["task_uid"]: row for row in matrix["rows"]}
    # wordcount passed on baseline, partially on opt; second passed on baseline,
    # failed on opt — the weak cell is (second, v-opt)
    assert by_task["wordcount-001@1.0.0"]["cells"]["v-base"] == 1.0
    assert by_task["wordcount-001@1.0.0"]["cells"]["v-opt"] == 0.9
    assert by_task["second-001@1.0.0"]["cells"]["v-opt"] == 0.2
    assert by_task["second-001@1.0.0"]["cells"]["v-base"] == 1.0

    body = client.get("/experiments/test-exp@1.0.0").text
    assert "Task &times; Configuration Matrix" in body
    assert 'data-score="0.2"' in body
    assert 'class="matrix-chip matrix-low"' in body


def test_the_dashboard_shows_which_runs_are_still_going(database_url: str) -> None:
    """A dashboard that only counts finished runs cannot say what is happening.

    A run in a non-terminal state is listed with its state and its age, and the
    set of terminal states is read from the lifecycle, so a state added there
    needs no change here. An empty list is a good answer, not an error.
    """
    store = _seeded_store(database_url)
    store.record_run(
        {
            "run_uid": "run-running",
            "task_uid": "wordcount-001@1.0.0",
            "agent_id": "codex",
            "agent_version": "1.0",
            "state": "executing",
            "started_at": "2026-11-06T18:00:00+00:00",
        },
        experiment_uid="test-exp@1.0.0",
        variant_uid="v-base",
        task=_task_stub(),
    )
    client = TestClient(create_app(database_url=database_url))

    active = client.get("/api/active-runs").json()
    # only the run that has not reached a terminal state is listed
    assert [run["uid"] for run in active] == ["run-running"]
    assert active[0]["status"] == "executing"
    assert active[0]["task_uid"] == "wordcount-001@1.0.0"

    body = client.get("/").text
    assert 'id="liveStrip"' in body and 'id="liveBody"' in body

    script = client.get("/static/js/app.js").text
    assert "fetchActiveRuns" in script and "tickLiveElapsed" in script


def test_the_price_table_is_read_from_the_project(tmp_path) -> None:
    """A cost is estimated from a table the operator wrote, never invented.

    Without the table there is no number and the pages say so; with it, a model
    is priced by name or by the default, and an unlisted model is left unpriced
    rather than guessed at.
    """
    from bench_ui.pricing import estimate_run_cost, format_cost, load_price_table

    empty = load_price_table(tmp_path)
    assert not empty
    assert format_cost(None) == "not recorded"

    (tmp_path / "pricing.yaml").write_text(
        "currency: USD\n"
        "models:\n"
        '  "*": {input: 1.0, output: 4.0}\n'
        "  qwen/cheap: {input: 0.10, output: 0.40}\n",
        encoding="utf-8",
    )
    table = load_price_table(tmp_path)
    assert table
    assert table.source.name == "pricing.yaml"

    # a named model uses its own price, not the default
    priced = estimate_run_cost(table, "qwen/cheap", {"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert priced == 0.5
    # an unlisted model falls back to the default
    default = estimate_run_cost(table, "other/model", {"input_tokens": 1_000_000, "output_tokens": 0})
    assert default == 1.0
    # a run that stated no tokens has no cost
    assert estimate_run_cost(table, "qwen/cheap", {}) is None
    assert format_cost(0.5) == "≈ $0.50"


def test_a_table_without_prices_is_no_table(tmp_path) -> None:
    """Half a file is not an estimate: a broken table reads as no table at all."""
    from bench_ui.pricing import load_price_table

    (tmp_path / "pricing.yaml").write_text("models: [not, a, mapping]\n", encoding="utf-8")
    assert not load_price_table(tmp_path)

    (tmp_path / "pricing.yaml").write_text("currency: USD\n", encoding="utf-8")
    assert not load_price_table(tmp_path)


def test_the_dashboard_estimates_cost_from_the_price_table(database_url: str, tmp_path) -> None:
    """The ledger's cost line names the file the estimate came from."""
    # the seeded runs record no model, so only a default price can reach them;
    # a table that names only a model nobody ran would price nothing, which is
    # the correct answer for that table, not a bug in the estimate
    (tmp_path / "pricing.yaml").write_text(
        "currency: USD\nmodels:\n  \"*\": {input: 1.0, output: 4.0}\n",
        encoding="utf-8",
    )
    _seeded_store(database_url)
    service = BenchDataService(database_url=database_url, project_root=tmp_path)
    estimate = service.estimate_total_cost(service.get_history().runs)
    assert estimate["total"] is not None
    assert estimate["priced_runs"] == 2
    assert estimate["unpriced_runs"] == 0

    ledger = {row["label"]: row for row in service.get_dashboard_stats()}
    assert ledger["cost"]["value"].startswith("≈ $")
    assert "pricing.yaml" in ledger["cost"]["hint"]

    # without a table the same line says it is not recorded
    bare = BenchDataService(database_url=database_url, project_root=tmp_path / "nowhere")
    bare_ledger = {row["label"]: row for row in bare.get_dashboard_stats()}
    assert bare_ledger["cost"]["value"] == "not recorded"
    assert bare_ledger["cost"]["hint"] is None


def test_two_runs_compare_their_changes_line_by_line(database_url: str, tmp_path) -> None:
    """Two answers are not compared until the answers themselves are diffed.

    Each run's change artifact is read and shown as the lines each side added
    or dropped; a run that recorded no change is reported as missing rather
    than diffed against nothing, and a pair where neither recorded one is no
    diff at all.
    """
    store = _seeded_store(database_url)
    first = tmp_path / "first.patch"
    first.write_text("--- a\n+++ b\n context line\n-removed by second\n+added by first\n", encoding="utf-8")
    second = tmp_path / "second.patch"
    second.write_text("--- a\n+++ b\n context line\n+added by second\n", encoding="utf-8")
    store.register_artifacts("run-001", [first])
    store.register_artifacts("run-002", [second])

    client = TestClient(create_app(database_url=database_url))
    comparison = client.get("/api/compare/runs?run_a=run-001&run_b=run-002").json()
    diff = comparison["artifact_diff"]
    assert diff["present_a"] and diff["present_b"]

    kinds = [(row["type"], row["text"]) for row in diff["rows"]]
    assert ("same", " context line") in kinds
    assert ("removed", "-removed by second") in kinds or any(
        kind == "removed" and "removed by second" in text for kind, text in kinds
    )
    assert any(kind == "added" and "added by second" in text for kind, text in kinds)

    body = client.get("/compare?run_a=run-001&run_b=run-002").text
    assert "Change Diff" in body
    assert "added by second" in body


def test_two_runs_without_change_artifacts_have_no_diff(database_url: str) -> None:
    """No artifact on either side is not an empty diff; it is no comparison."""
    _seeded_store(database_url)
    service = BenchDataService(database_url=database_url)
    comparison = service.compare_runs_side_by_side("run-001", "run-002")
    assert comparison["artifact_diff"] is None

def test_the_palette_switches_between_dark_and_light(database_url: str) -> None:
    """A reader watching a wall display and a reader on a laptop want different palettes.

    The theme is one swap of the variables the pages already read, so the test
    does not check colours, it checks the seam: a button in the navigation, the
    stored choice applied before the sheet paints (so no dark frame flashes in
    front of a light page), one palette defined as a block of variables, and the
    charts told to redraw because a canvas cannot follow a variable.
    """
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/").text
    assert 'id="themeToggle"' in body
    # the choice is applied before the stylesheet paints
    assert body.index("akbench_theme") < body.index("style.css")
    assert 'data-theme' in body

    css = client.get("/static/css/style.css").text
    assert '[data-theme="light"]' in css

    script = client.get("/static/js/app.js").text
    assert "initThemeToggle" in script
    assert "akbench:theme" in script
    # charts read their ink from the theme instead of fixing it
    assert "akbenchThemeColors" in script


def test_the_runs_table_is_driven_from_the_keyboard(database_url: str) -> None:
    """A reader who lives at the keyboard should not have to reach for the mouse.

    The runs page says how it is driven, and the script behind it moves a cursor
    with the arrow keys, opens the run under the cursor on Enter, and drops into
    the filter search on "/". The keys belong to whatever is being typed into,
    so the script guards against stealing them from an input or an open modal.
    """
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/runs").text
    assert "kbd-hint" in body
    assert "<kbd>" in body

    script = client.get("/static/js/app.js").text
    assert "initRunsKeyNav" in script
    assert "runsKeyNavFocus" in script
    assert "row-focused" in script
    assert "filterSearch" in script


def test_the_runs_page_exports_its_filtered_rows(database_url: str) -> None:
    """A filtered table is an answer to a question; the reader should be able to take it.

    The runs page offers the rows the filters match as CSV and as Markdown, so
    the same answer can be dropped into a notebook or a message. The exporter
    reads the numbers the API holds, not the strings the page prettified.
    """
    _seeded_store(database_url)
    client = TestClient(create_app(database_url=database_url))

    body = client.get("/runs").text
    assert 'id="btnCopyCsv"' in body
    assert 'id="btnCopyMarkdown"' in body

    script = client.get("/static/js/app.js").text
    assert "copyRunsTable" in script
    assert "tableToCsv" in script
    assert "tableToMarkdown" in script
    # the export comes from the API, so the filter state is the live one
    assert "currentRunsForExport" in script

