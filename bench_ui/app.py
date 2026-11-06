"""FastAPI application for AK-Bench UI: real-time dashboard and comparison studio."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bench_ui.service import BenchDataService

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app(database_url: str | None = None, project_root: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="AK-Bench UI",
        description="Real-time interactive dashboard and comparison studio for AK-Bench",
        version="0.1.0",
    )

    # Static files & templates
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Shared data service instance
    service = BenchDataService(database_url=database_url, project_root=project_root)

    # ------------------------------------------------------------- HTML Web Pages
    @app.get("/", response_class=HTMLResponse)
    async def dashboard_page(request: Request):
        overview = service.get_overview()
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
                "database_url": service.display_database_url,
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    async def runs_page(
        request: Request,
        experiment_uid: str | None = None,
        task_uid: str | None = None,
        variant_uid: str | None = None,
        verdict: str | None = None,
        status: str | None = None,
        agent: str | None = None,
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
                "database_url": service.display_database_url,
            },
        )

    @app.get("/analytics", response_class=HTMLResponse)
    async def analytics_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="analytics.html",
            context={"active_page": "analytics", "database_url": service.database_url},
        )

    @app.get("/api/analytics/data")
    async def api_analytics_data():
        return service.get_analytics_dataset()

    @app.get("/compare", response_class=HTMLResponse)
    async def compare_page(
        request: Request,
        run_a: str | None = None,
        run_b: str | None = None,
        configs: list[str] = Query(default=[]),
    ):
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
                "run_a_uid": run_a,
                "run_b_uid": run_b,
                "config_comparison": config_comparison,
                "database_url": service.display_database_url,
            },
        )

    @app.get("/experiments", response_class=HTMLResponse)
    async def experiments_page(request: Request):
        experiments = service.get_experiments()
        return templates.TemplateResponse(
            request=request,
            name="experiments.html",
            context={
                "active_page": "experiments",
                "experiments": experiments,
                "database_url": service.display_database_url,
            },
        )

    @app.get("/experiments/{experiment_uid}", response_class=HTMLResponse)
    async def experiment_detail_page(request: Request, experiment_uid: str):
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
                "snapshots": detail["snapshots"],
                "runs": detail["runs"],
                "database_url": service.display_database_url,
            },
        )

    @app.get("/tasks", response_class=HTMLResponse)
    async def tasks_page(request: Request):
        tasks = service.get_tasks()
        return templates.TemplateResponse(
            request=request,
            name="tasks.html",
            context={
                "active_page": "tasks",
                "tasks": tasks,
                "database_url": service.display_database_url,
            },
        )

    @app.get("/tasks/{task_uid}", response_class=HTMLResponse)
    async def task_detail_page(request: Request, task_uid: str):
        detail = service.get_task_detail(task_uid)
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
                "database_url": service.display_database_url,
            },
        )

    # ------------------------------------------------------------- REST JSON API
    @app.get("/api/overview")
    async def api_overview():
        return service.get_overview()

    @app.get("/api/runs")
    async def api_runs(
        experiment_uid: str | None = None,
        task_uid: str | None = None,
        variant_uid: str | None = None,
        verdict: str | None = None,
        status: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        search: str | None = None,
        sort_by: str = "started_at",
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ):
        return service.get_filtered_runs(
            experiment_uid=experiment_uid,
            task_uid=task_uid,
            variant_uid=variant_uid,
            verdict=verdict,
            status=status,
            agent=agent,
            model=model,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/runs/{run_uid}")
    async def api_run_detail(run_uid: str):
        detail = service.get_run_detail(run_uid)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run '{run_uid}' not found")
        return detail

    @app.get("/api/artifacts/{run_uid}/{artifact_kind}")
    async def api_artifact_content(run_uid: str, artifact_kind: str):
        artifact = service.get_artifact_content(run_uid, artifact_kind)
        if not artifact:
            raise HTTPException(
                status_code=404,
                detail=f"Artifact '{artifact_kind}' for run '{run_uid}' not found",
            )
        return artifact

    @app.get("/api/compare/configurations")
    async def api_compare_configurations(configs: list[str] = Query(default=[])):
        return service.compare_configurations(configs)

    @app.get("/api/compare/runs")
    async def api_compare_runs(run_a: str, run_b: str):
        result = service.compare_runs_side_by_side(run_a, run_b)
        if not result:
            raise HTTPException(status_code=404, detail="One or both runs were not found")
        return result

    @app.get("/api/experiments")
    async def api_experiments():
        return service.get_experiments()

    @app.get("/api/tasks")
    async def api_tasks():
        return service.get_tasks()

    return app


app = create_app()
