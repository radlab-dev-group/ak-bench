"""FastAPI application for AK-Bench UI: real-time dashboard and comparison studio."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bench_ui.middleware import SecurityMiddleware
from bench_ui.security import (
    SecuritySettings,
    load_security_settings,
    request_shows_ground_truth,
)
from bench_ui.service import MAX_PAGE_SIZE, BenchDataService

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _empty_overview() -> dict[str, Any]:
    """The dashboard's shape when the database cannot be read.

    A dashboard that cannot reach its history says so, rather than showing a
    zero-filled world: the numbers would be true of nothing.
    """
    return {
        "summary": {
            "runs": 0,
            "evaluated": 0,
            "passed": 0,
            "not_passed": 0,
            "success_rate": None,
            "mean_score": None,
            "scored_runs": 0,
            "mean_duration_seconds": None,
            "measured_durations": 0,
            "total_tokens": 0,
            "token_runs": 0,
            "input_tokens": 0,
            "input_token_runs": 0,
            "output_tokens": 0,
            "output_token_runs": 0,
            "tool_calls": 0,
            "tool_call_runs": 0,
            "statuses": [],
        },
        "ranking": [],
        "recent_runs": [],
        "experiments_count": 0,
        "tasks_count": 0,
        "variants_count": 0,
        "verdicts": {},
        "statuses": [],
    }


def create_app(
    database_url: str | None = None,
    project_root: Path | None = None,
    namespace: str | None = None,
    security: SecuritySettings | None = None,
    *,
    api_docs: bool = False,
) -> FastAPI:
    """Build the dashboard.

    ``security`` off the shelf comes from the ``AKBENCH_UI_*`` environment, which
    is what the command line sets from its own options; pass it directly to
    embed the app with a posture of your own.

    ``api_docs`` is off because an interactive map of every endpoint, served to
    anyone who guesses the path, is a convenience for the operator and a
    reconnaissance shortcut for everyone else.
    """
    settings = security if security is not None else load_security_settings()
    app = FastAPI(
        title="AK-Bench UI",
        description="Real-time interactive dashboard and comparison studio for AK-Bench",
        version="0.1.0",
        docs_url="/docs" if api_docs else None,
        redoc_url="/redoc" if api_docs else None,
        openapi_url="/openapi.json" if api_docs else None,
    )
    app.state.security = settings
    if settings.misconfiguration:
        log.error("the dashboard will refuse every request: %s", settings.misconfiguration)

    # Credentials and the security headers, before any of the routes below and
    # before the 404 Starlette produces for a path that is not there.
    app.add_middleware(SecurityMiddleware, settings=settings)

    # Static files & templates
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Shared data service instance. The connection comes from the project
    # configuration (.env), so the UI and the CLI read the same database.
    if namespace and not database_url:
        import os

        os.environ.setdefault("AKBENCH__DATABASE__POSTGRES__NAMESPACE", namespace)
    service = BenchDataService(database_url=database_url, project_root=project_root)
    # The reader's view of the connection: is there history, and what to do if
    # not. The operator's fuller view stays in the service and the log.
    database = service.connectivity_public()
    service.database_info = database

    # ------------------------------------------------------------- HTML Web Pages
    @app.get("/api/database")
    def api_database():
        return database

    @app.get("/", response_class=HTMLResponse)
    def dashboard_page(request: Request):
        overview = _empty_overview() if service.connection_error else service.get_overview()
        model_comparison = [] if service.connection_error else service.get_model_comparison()
        stats = [] if service.connection_error else service.get_dashboard_stats()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "active_page": "dashboard",
                "summary": overview["summary"],
                "ranking": overview["ranking"],
                "recent_runs": overview["recent_runs"],
                "experiments_count": overview["experiments_count"],
                "tasks_count": overview["tasks_count"],
                "variants_count": overview["variants_count"],
                "verdicts": overview["verdicts"],
                "statuses": overview["statuses"],
                "model_comparison": model_comparison,
                "stats": stats,
                "database": database,
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    def runs_page(
        request: Request,
        experiment_uid: str | None = None,
        task_uid: str | None = None,
        variant_uid: str | None = None,
        verdict: str | None = None,
        status: str | None = None,
        agent: str | None = None,
        runtime: str | None = None,
        model: str | None = None,
        search: str | None = None,
    ):
        data = service.get_filtered_runs(
            experiment_uid=experiment_uid,
            task_uid=task_uid,
            variant_uid=variant_uid,
            verdict=verdict,
            status=status,
            agent=agent,
            runtime=runtime,
            model=model,
            search=search,
            limit=200,
        )
        return templates.TemplateResponse(
            request=request,
            name="runs.html",
            context={
                "active_page": "runs",
                "runs": data["runs"],
                "total": data["total"],
                "filter_options": data["filter_options"],
                # The filters the page was asked for, so a link from an agent
                # or runtime page shows which slice of the history it opened.
                "filters": {
                    "experiment_uid": experiment_uid,
                    "task_uid": task_uid,
                    "variant_uid": variant_uid,
                    "verdict": verdict,
                    "status": status,
                    "agent": agent,
                    "runtime": runtime,
                    "model": model,
                    "search": search,
                },
                "database": database,
            },
        )

    @app.get("/analytics", response_class=HTMLResponse)
    def analytics_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="analytics.html",
            context={
                "active_page": "analytics",
                "database": database,
            },
        )

    @app.get("/api/analytics/data")
    def api_analytics_data():
        return service.get_analytics_dataset()

    @app.get("/compare", response_class=HTMLResponse)
    def compare_page(
        request: Request,
        run_a: str | None = None,
        run_b: str | None = None,
        view: str | None = None,
        configs: list[str] = Query(default=[]),
    ):
        run_a, run_b = run_a or None, run_b or None
        run_options = service.get_run_options()
        # The run diff is a view of its own, and it opens on two runs already
        # chosen: asking a reader to type two uids they do not know is not an
        # answer, it is the question this page is meant to help with.
        show_runs = view == "runs" or (run_a is not None and run_b is not None)
        if show_runs and not (run_a and run_b) and len(run_options) >= 2:
            run_a = run_a or run_options[0]["uid"]
            run_b = run_b or run_options[1]["uid"]
        run_diff = None
        if run_a and run_b:
            run_diff = service.compare_runs_side_by_side(run_a, run_b)

        config_comparison = service.compare_configurations(configs)
        return templates.TemplateResponse(
            request=request,
            name="compare.html",
            context={
                "active_page": "compare",
                "run_diff": run_diff,
                "show_runs": show_runs,
                "run_a_uid": run_a,
                "run_b_uid": run_b,
                "run_options": run_options,
                "config_comparison": config_comparison,
                "database": database,
            },
        )

    @app.get("/experiments", response_class=HTMLResponse)
    def experiments_page(request: Request):
        experiments = service.get_experiments()
        return templates.TemplateResponse(
            request=request,
            name="experiments.html",
            context={
                "active_page": "experiments",
                "experiments": experiments,
                "database": database,
            },
        )

    @app.get("/experiments/{experiment_uid}", response_class=HTMLResponse)
    def experiment_detail_page(request: Request, experiment_uid: str):
        detail = service.get_experiment_detail(experiment_uid)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Experiment '{experiment_uid}' not found")
        return templates.TemplateResponse(
            request=request,
            name="experiment_detail.html",
            context={
                "active_page": "experiments",
                "experiment": detail["experiment"],
                "summary": detail["summary"],
                "ranking": detail["ranking"],
                "variants": detail["variants"],
                "variant_summaries": detail["variant_summaries"],
                "score_matrix": detail.get("score_matrix"),
                "snapshots": detail["snapshots"],
                "runs": detail["runs"],
                "database": database,
            },
        )

    @app.get("/tasks", response_class=HTMLResponse)
    def tasks_page(request: Request):
        tasks = service.get_tasks()
        return templates.TemplateResponse(
            request=request,
            name="tasks.html",
            context={
                "active_page": "tasks",
                "tasks": tasks,
                "database": database,
            },
        )

    @app.get("/tasks/{task_uid}", response_class=HTMLResponse)
    def task_detail_page(request: Request, task_uid: str):
        see_key = request_shows_ground_truth(request, settings)
        detail = service.get_task_detail(task_uid, include_ground_truth=see_key)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Task '{task_uid}' not found")
        return templates.TemplateResponse(
            request=request,
            name="task_detail.html",
            context={
                "active_page": "tasks",
                "task": detail["task"],
                "summary": detail["summary"],
                "definition": detail.get("definition"),
                "runs": detail["runs"],
                "files": service.get_task_files(task_uid, include_ground_truth=see_key),
                "shows_ground_truth": see_key,
                "database": database,
            },
        )

    @app.get("/agents", response_class=HTMLResponse)
    def agents_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="agents.html",
            context={
                "active_page": "agents",
                "agents": service.get_agents(),
                "database": database,
            },
        )

    @app.get("/agents/{agent_id}", response_class=HTMLResponse)
    @app.get("/agents/{agent_id}/{version}", response_class=HTMLResponse)
    def agent_detail_page(request: Request, agent_id: str, version: str | None = None):
        agents = [row for row in service.get_agents() if row["id"] == agent_id]
        if not agents:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not recorded")
        if version is not None:
            wanted = [row for row in agents if row["version"] == version]
            if not wanted:
                raise HTTPException(
                    status_code=404, detail=f"Agent '{agent_id}' has no version '{version}'"
                )
            agents = wanted
        return templates.TemplateResponse(
            request=request,
            name="agent_detail.html",
            context={
                "active_page": "agents",
                "agent_id": agent_id,
                "agents": agents,
                "database": database,
            },
        )

    @app.get("/runtimes", response_class=HTMLResponse)
    def runtimes_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="runtimes.html",
            context={
                "active_page": "runtimes",
                "runtimes": service.get_runtimes(),
                "database": database,
            },
        )

    @app.get("/runtimes/{runtime_id}", response_class=HTMLResponse)
    @app.get("/runtimes/{runtime_id}/{version}", response_class=HTMLResponse)
    def runtime_detail_page(request: Request, runtime_id: str, version: str | None = None):
        runtimes = [row for row in service.get_runtimes() if row["id"] == runtime_id]
        if not runtimes:
            raise HTTPException(status_code=404, detail=f"Runtime '{runtime_id}' not recorded")
        if version is not None:
            wanted = [row for row in runtimes if row["version"] == version]
            if not wanted:
                raise HTTPException(
                    status_code=404, detail=f"Runtime '{runtime_id}' has no version '{version}'"
                )
            runtimes = wanted
        return templates.TemplateResponse(
            request=request,
            name="runtime_detail.html",
            context={
                "active_page": "runtimes",
                "runtime_id": runtime_id,
                "runtimes": runtimes,
                "database": database,
            },
        )

    # ------------------------------------------------------------- REST JSON API
    @app.get("/api/overview")
    def api_overview():
        return service.get_overview()

    @app.get("/api/runs")
    def api_runs(
        experiment_uid: str | None = None,
        task_uid: str | None = None,
        variant_uid: str | None = None,
        verdict: str | None = None,
        status: str | None = None,
        agent: str | None = None,
        runtime: str | None = None,
        model: str | None = None,
        search: str | None = None,
        sort_by: str = "started_at",
        sort_order: str = "desc",
        limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
    ):
        return service.get_filtered_runs(
            experiment_uid=experiment_uid,
            task_uid=task_uid,
            variant_uid=variant_uid,
            verdict=verdict,
            status=status,
            agent=agent,
            runtime=runtime,
            model=model,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/runs/{run_uid}")
    def api_run_detail(run_uid: str):
        detail = service.get_run_detail(run_uid)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run '{run_uid}' not found")
        return detail

    @app.get("/api/artifacts/{run_uid}/{artifact_kind}")
    def api_artifact_content(run_uid: str, artifact_kind: str):
        artifact = service.get_artifact_content(run_uid, artifact_kind)
        if not artifact:
            raise HTTPException(
                status_code=404,
                detail=f"Artifact '{artifact_kind}' for run '{run_uid}' not found",
            )
        return artifact

    @app.get("/api/compare/configurations")
    def api_compare_configurations(configs: list[str] = Query(default=[])):
        return service.compare_configurations(configs)

    @app.get("/api/compare/runs")
    def api_compare_runs(run_a: str, run_b: str):
        result = service.compare_runs_side_by_side(run_a, run_b)
        if not result:
            raise HTTPException(status_code=404, detail="One or both runs were not found")
        return result

    @app.get("/api/experiments")
    def api_experiments():
        return service.get_experiments()

    @app.get("/api/tasks/{task_uid}/files")
    def api_task_files(request: Request, task_uid: str):
        see_key = request_shows_ground_truth(request, settings)
        if service.get_task_detail(task_uid, include_ground_truth=see_key) is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_uid}' not found")
        return service.get_task_files(task_uid, include_ground_truth=see_key)

    @app.get("/api/tasks/{task_uid}/files/{path:path}")
    def api_task_file(request: Request, task_uid: str, path: str):
        see_key = request_shows_ground_truth(request, settings)
        if service.get_task_detail(task_uid, include_ground_truth=see_key) is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_uid}' not found")
        row = service.get_task_file(task_uid, path, include_ground_truth=see_key)
        if row is None:
            raise HTTPException(status_code=404, detail="File not recorded for this task")
        return row

    @app.get("/api/tasks/{task_uid}/download.zip")
    def api_task_code_zip(request: Request, task_uid: str):
        """The task's recorded code as one archive, named after the task.

        The archive is the task as it was recorded, which for a reader who is not
        grading it means without the hidden tests and the planted defect: a zip of
        the answer key is the same leak as showing it on the page, only easier.
        """
        see_key = request_shows_ground_truth(request, settings)
        packed = service.get_task_code_zip(task_uid, include_ground_truth=see_key)
        if packed is None:
            raise HTTPException(status_code=404, detail="No task code recorded")
        payload, filename = packed
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"content-disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/tasks")
    def api_tasks():
        return service.get_tasks()

    return app


app = create_app()
