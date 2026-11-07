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
