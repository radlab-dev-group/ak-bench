"""Data service for AK-Bench UI: querying, filtering, comparisons and analytics."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from akbench.config.loader import load_settings, resolve_database_url
from akbench.core.errors import ConfigError, DatabaseError
from akbench.datasets import Dataset, TaskLoadError
from akbench.reporting.data import (
    HistoryData,
    build_experiment_report,
    build_task_report,
    collect_history,
    configuration_ranking,
    duration_seconds,
    score_of,
    summarize_runs,
    unverified_configurations,
    verdict_of,
)
from akbench.storage.db import (
    create_db_engine,
    engine_is_reachable,
    namespace_of_url,
    session_scope,
)
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import schema_status
from akbench.storage.models import (
    Artifact,
    EvaluationRecord,
    TaskRun,
)


def _safe_load_json(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


class BenchDataService:
    """Provides high-level data querying, aggregation, filtering and comparisons for the UI.

    The connection comes from the project's configuration, so the UI and the
    CLI read the same ``.env``: the backend, the PostgreSQL parameters and the
    namespace are the ones the operator already set. A problem with that
    configuration is reported, not hidden behind an empty dashboard.
    """

    def __init__(self, database_url: str | None = None, project_root: Path | None = None) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.config_error: str | None = None
        self.dotenv_path: Path | None = None
        self.source: str | None = None
        self.settings: object | None = None
        try:
            loaded = load_settings(None, project_root=self.project_root)
            self.settings = loaded.settings
            self.dotenv_path = loaded.dotenv_path
            self.source = loaded.describe()
        except ConfigError as exc:
            self.config_error = str(exc)

        if database_url:
            self.database_url = database_url
            self.namespace: str | None = None
        elif self.settings is not None:
            self.database_url = resolve_database_url(self.settings)
            namespace = (
                self.settings.database.postgres.namespace
                if self.settings.database.backend == "postgres"
                else None
            )
            self.namespace = namespace_of_url(self.database_url) or namespace
        else:
            default_sqlite = (self.project_root / "data" / "akbench.sqlite").resolve()
            self.database_url = f"sqlite:///{default_sqlite}"
            self.namespace = None

        self.engine: Engine = create_db_engine(self.database_url)
        self.store = HistoryStore(self.engine)
        self.connection_error: str | None = None
        try:
            engine_is_reachable(self.engine)
            self.revision = schema_status(self.database_url).current
        except DatabaseError as exc:
            self.connection_error = str(exc)
        self._dataset: Dataset | None = None
        self._dataset_loaded = False

    def connectivity(self) -> dict[str, Any]:
        """What the UI is looking at: the backend, the namespace, the error."""
        return {
            # The address of the database never reaches the UI: a status is
            # what a reader can act on, and a URL is a credential in all but
            # name.
            "backend": (
                self.settings.database.backend if self.settings is not None else "sqlite"
            ),
            "namespace": self.namespace,
            "reachable": self.connection_error is None,
            "revision": self.revision if not self.connection_error else None,
            "error": self.connection_error,
        }

    def get_dataset(self) -> Dataset | None:
        if not self._dataset_loaded:
            self._dataset_loaded = True
            datasets_dir = self.project_root / "datasets"
            if datasets_dir.is_dir():
                try:
                    self._dataset = Dataset.load(datasets_dir, base_dir=self.project_root)
                except TaskLoadError:
                    self._dataset = None
        return self._dataset

    def get_history(self) -> HistoryData:
        return collect_history(self.store)

    # ------------------------------------------------------------- Overview
    def get_overview(self) -> dict[str, Any]:
        history = self.get_history()
        runs = history.runs
        summary = summarize_runs(runs)

        # Verdict counts
        verdicts: dict[str, int] = {}
        for r in runs:
            v = verdict_of(r) or "unverified"
            verdicts[v] = verdicts.get(v, 0) + 1

        # Status counts
        statuses: dict[str, int] = {}
        for r in runs:
            st = str(r.get("status") or "unknown")
            statuses[st] = statuses.get(st, 0) + 1

        # Configuration ranking
        ranking = configuration_ranking(runs, history.variants)

        # Recent runs (last 15 ordered by start descending)
        ordered_runs = sorted(runs, key=lambda r: str(r.get("started_at") or ""), reverse=True)
        recent_runs = [self._format_run_summary(r, history) for r in ordered_runs[:15]]

        # Aggregate task performance
        task_stats = []
        for task in history.tasks:
            t_uid = task.get("uid")
            t_runs = [r for r in runs if r.get("task_uid") == t_uid]
            if t_runs:
                t_sum = summarize_runs(t_runs)
                task_stats.append(
                    {
                        "task_uid": t_uid,
                        "category": task.get("category"),
                        "difficulty": task.get("difficulty"),
                        "runs": t_sum["runs"],
                        "passed": t_sum["passed"],
                        "success_rate": t_sum["success_rate"],
                        "mean_score": t_sum["mean_score"],
                        "mean_duration": t_sum["mean_duration_seconds"],
                        "total_tokens": t_sum["total_tokens"],
                    }
                )

        return {
            "summary": summary,
            "verdicts": verdicts,
            "statuses": statuses,
            "ranking": ranking,
            "recent_runs": recent_runs,
            "experiments_count": len(history.experiments),
            "tasks_count": len(history.tasks),
            "variants_count": sum(len(v) for v in history.variants.values()),
            "task_stats": task_stats,
            "unverified": unverified_configurations(history),
        }

    # -------------------------------------------------------- Filtered Runs
    def get_filtered_runs(
        self,
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
    ) -> dict[str, Any]:
        history = self.get_history()
        runs = history.runs

        filtered = []
        for r in runs:
            # Experiment filter
            if experiment_uid and r.get("experiment_uid") != experiment_uid:
                continue
            # Task filter
            if task_uid and r.get("task_uid") != task_uid:
                continue
            # Variant filter
            if variant_uid and r.get("variant_uid") != variant_uid:
                continue
            # Verdict filter
            if verdict:
                r_verdict = verdict_of(r)
                if (verdict == "unverified" and r_verdict is not None) or (
                    verdict != "unverified" and r_verdict != verdict
                ):
                    continue
            # Status filter
            if status and r.get("status") != status:
                continue
            # Agent filter
            if agent and r.get("agent") != agent:
                continue
            # Model filter
            if model:
                obs_model = r.get("observed_model") or r.get("requested_model")
                if obs_model != model:
                    continue
            # General text search
            if search:
                query = search.lower().strip()
                matchable = (
                    f"{r.get('uid')} {r.get('task_uid')} {r.get('experiment_uid')} "
                    f"{r.get('variant_uid')} {r.get('agent')} {r.get('observed_model')} "
                    f"{r.get('status')} {verdict_of(r)}"
                ).lower()
                if query not in matchable:
                    continue

            filtered.append(r)

        total_matched = len(filtered)

        # Sorting
        def sort_key(run: dict[str, Any]) -> Any:
            if sort_by == "started_at":
                return str(run.get("started_at") or "")
            elif sort_by == "duration":
                return duration_seconds(run) or 0.0
            elif sort_by == "score":
                return score_of(run) if score_of(run) is not None else -1.0
            elif sort_by == "tokens":
                obs = run.get("observations") or {}
                return obs.get("total_tokens") or 0
            elif sort_by == "task_uid":
                return str(run.get("task_uid") or "")
            elif sort_by == "verdict":
                return str(verdict_of(run) or "")
            elif sort_by == "status":
                return str(run.get("status") or "")
            return str(run.get("uid") or "")

        reverse = sort_order.lower() == "desc"
        filtered.sort(key=sort_key, reverse=reverse)

        paginated = filtered[offset : offset + limit] if limit > 0 else filtered

        formatted_runs = [self._format_run_summary(r, history) for r in paginated]

        # Available filter options for UI dropdowns
        all_experiments = sorted(
            {str(r.get("experiment_uid")) for r in runs if r.get("experiment_uid")}
        )
        all_tasks = sorted({str(r.get("task_uid")) for r in runs if r.get("task_uid")})
        all_verdicts = sorted({verdict_of(r) for r in runs if verdict_of(r)})
        all_statuses = sorted({str(r.get("status")) for r in runs if r.get("status")})
        all_models = sorted(
            {
                str(r.get("observed_model") or r.get("requested_model"))
                for r in runs
                if r.get("observed_model") or r.get("requested_model")
            }
        )
        all_agents = sorted({str(r.get("agent")) for r in runs if r.get("agent")})

        # Summary of the filtered subset
        filtered_summary = summarize_runs(filtered) if filtered else summarize_runs([])

        return {
            "total": total_matched,
            "limit": limit,
            "offset": offset,
            "runs": formatted_runs,
            "summary": filtered_summary,
            "filter_options": {
                "experiments": all_experiments,
                "tasks": all_tasks,
                "verdicts": all_verdicts,
                "statuses": all_statuses,
                "models": all_models,
                "agents": all_agents,
            },
        }

    # ---------------------------------------------------------- Run Details
    def get_run_detail(self, run_uid: str) -> dict[str, Any] | None:
        run = self.store.run(run_uid)
        if not run:
            return None

        history = self.get_history()
        events = self.store.events(run_uid)
        plugins = self.store.plugin_observations(run_uid)

        # Fetch evaluation details json from database
        eval_record_details = None
        eval_record_artifacts = None
        evaluator_info = {}
        with session_scope(self.engine) as session:
            task_run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if task_run:
                eval_row = session.scalar(
                    select(EvaluationRecord).where(EvaluationRecord.run_id == task_run.id)
                )
                if eval_row:
                    eval_record_details = _safe_load_json(eval_row.details_json)
                    eval_record_artifacts = _safe_load_json(eval_row.artifacts_json)
                    evaluator_info = {
                        "evaluator_id": eval_row.evaluator_id,
                        "evaluator_version": eval_row.evaluator_version,
                        "duration_seconds": eval_row.duration_seconds,
                        "score": eval_row.score,
                        "verdict": eval_row.verdict,
                        "passed": eval_row.passed,
                        "failed": eval_row.failed,
                        "skipped": eval_row.skipped,
                        "total": eval_row.total,
                    }

        # Resolve variant config
        variant_values = {}
        exp_variants = history.variants.get(str(run.get("experiment_uid")), [])
        for v in exp_variants:
            if v.get("uid") == run.get("variant_uid"):
                variant_values = v.get("values") or {}
                break

        # Check if task description is available
        task_meta = history.task(str(run.get("task_uid"))) or {}
        dataset = self.get_dataset()
        task_instruction = None
        if dataset and run.get("task_uid"):
            with contextlib.suppress(Exception):
                task_obj = dataset.get(run["task_uid"])
                if task_obj:
                    task_instruction = task_obj.instruction

        duration = duration_seconds(run)
        score = score_of(run)
        verdict = verdict_of(run)

        return {
            "run": run,
            "duration_seconds": duration,
            "score": score,
            "verdict": verdict,
            "events": events,
            "plugins": plugins,
            "variant_values": variant_values,
            "task_meta": task_meta,
            "task_instruction": task_instruction,
            "evaluation_details": eval_record_details,
            "evaluation_artifacts": eval_record_artifacts,
            "evaluator_info": evaluator_info,
            "artifacts": run.get("artifacts") or [],
        }

    # ----------------------------------------------------- Artifact Content
    def get_artifact_content(self, run_uid: str, artifact_kind: str) -> dict[str, Any] | None:
        with session_scope(self.engine) as session:
            task_run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if not task_run:
                return None
            artifact = session.scalar(
                select(Artifact).where(
                    Artifact.run_id == task_run.id, Artifact.kind == artifact_kind
                )
            )
            if not artifact:
                return None

            content_text = None
            if artifact.data is not None:
                try:
                    content_text = artifact.data.decode("utf-8")
                except UnicodeDecodeError:
                    content_text = f"<Binary data, size: {len(artifact.data)} bytes>"
            elif artifact.path and Path(artifact.path).is_file():
                try:
                    content_text = Path(artifact.path).read_text(encoding="utf-8", errors="replace")
                except Exception as ex:
                    content_text = f"<Error reading file: {ex}>"

            return {
                "kind": artifact.kind,
                "path": artifact.path,
                "content_type": artifact.content_type,
                "size_bytes": artifact.size_bytes,
                "checksum": artifact.checksum,
                "content": content_text,
            }

    # ---------------------------------------------------- Experiments & Tasks
    def get_experiments(self) -> list[dict[str, Any]]:
        history = self.get_history()
        results = []
        for exp in history.experiments:
            exp_uid = exp["uid"]
            exp_runs = [r for r in history.runs if r.get("experiment_uid") == exp_uid]
            summary = summarize_runs(exp_runs)
            variants = history.variants.get(exp_uid, [])
            results.append(
                {
                    "uid": exp_uid,
                    "title": exp.get("title") or exp_uid,
                    "description": exp.get("description"),
                    "type": exp.get("type"),
                    "descriptor": exp.get("descriptor"),
                    "validity": exp.get("validity"),
                    "runs_count": summary["runs"],
                    "passed_count": summary["passed"],
                    "success_rate": summary["success_rate"],
                    "mean_score": summary["mean_score"],
                    "mean_duration": summary["mean_duration_seconds"],
                    "total_tokens": summary["total_tokens"],
                    "variants_count": len(variants),
                    "created_at": exp.get("created_at"),
                    "updated_at": exp.get("updated_at"),
                }
            )
        return results

    def get_experiment_detail(self, experiment_uid: str) -> dict[str, Any] | None:
        history = self.get_history()
        if history.experiment(experiment_uid) is None:
            return None

        report = build_experiment_report(history, experiment_uid)
        variants = history.variants.get(experiment_uid, [])
        snapshots = self.store.snapshots(experiment_uid)
        ranking = configuration_ranking(report.runs, {experiment_uid: variants})

        # Per-variant summary breakdown
        variant_summaries = []
        for v in variants:
            v_uid = v.get("uid")
            v_runs = [r for r in report.runs if r.get("variant_uid") == v_uid]
            v_summary = summarize_runs(v_runs)
            variant_summaries.append(
                {
                    "variant": v,
                    "summary": v_summary,
                    "runs": [self._format_run_summary(r, history) for r in v_runs],
                }
            )

        return {
            "experiment": report.experiment,
            "summary": report.summary,
            "ranking": ranking,
            "variants": variants,
            "variant_summaries": variant_summaries,
            "snapshots": snapshots,
            "runs": [self._format_run_summary(r, history) for r in report.runs],
        }

    def get_tasks(self) -> list[dict[str, Any]]:
        history = self.get_history()
        results = []
        dataset = self.get_dataset()
        for task in history.tasks:
            t_uid = task["uid"]
            t_runs = [r for r in history.runs if r.get("task_uid") == t_uid]
            summary = summarize_runs(t_runs)
            doc_available = False
            if dataset:
                with contextlib.suppress(Exception):
                    doc_available = dataset.get(t_uid) is not None

            results.append(
                {
                    "uid": t_uid,
                    "task_id": task.get("id"),
                    "version": task.get("version"),
                    "category": task.get("category"),
                    "difficulty": task.get("difficulty"),
                    "evaluator": task.get("evaluator"),
                    "runs_count": summary["runs"],
                    "passed_count": summary["passed"],
                    "success_rate": summary["success_rate"],
                    "mean_score": summary["mean_score"],
                    "mean_duration": summary["mean_duration_seconds"],
                    "total_tokens": summary["total_tokens"],
                    "doc_available": doc_available,
                }
            )
        return results

    def get_task_detail(self, task_uid: str) -> dict[str, Any] | None:
        history = self.get_history()
        if history.task(task_uid) is None:
            return None

        report = build_task_report(history, task_uid, dataset=self.get_dataset())
        return {
            "task": report.task,
            "summary": report.summary,
            "definition": report.definition,
            "variants": report.variants,
            "runs": [self._format_run_summary(r, history) for r in report.runs],
        }

    # ------------------------------------------------ Cross-Comparison Matrix
    def compare_configurations(self, config_keys: list[str]) -> dict[str, Any]:
        """Deep comparison between two or more configuration labels or variant UIDs."""
        history = self.get_history()
        runs = history.runs
        variants_all = history.variants

        # Build full configuration ranking to get standardized config names and baseline comparisons
        ranking = configuration_ranking(runs, variants_all)
        ranking_map = {r["config"]: r for r in ranking}

        # If user passed empty, compare top 2-3 configurations
        if not config_keys:
            selected_configs = [r["config"] for r in ranking[:2]]
        else:
            selected_configs = [
                k
                for k in config_keys
                if k in ranking_map or any(r.get("variant_uid") == k for r in runs)
            ]

        # Map variant values to each config
        config_data = []
        for cfg_name in selected_configs:
            rank_info = ranking_map.get(cfg_name)
            # Find matching runs
            matching_runs = []
            for r in runs:
                var_uid = r.get("variant_uid")
                exp_uid = r.get("experiment_uid")
                v_list = variants_all.get(str(exp_uid), [])
                for v in v_list:
                    if v.get("uid") == var_uid:
                        # Check formatted config string
                        items = sorted(f"{k}={val}" for k, val in (v.get("values") or {}).items())
                        if ", ".join(items) == cfg_name or v.get("uid") == cfg_name:
                            matching_runs.append(r)
                        break

            summary = summarize_runs(matching_runs)
            config_data.append(
                {
                    "config_name": cfg_name,
                    "rank_info": rank_info,
                    "summary": summary,
                    "runs_count": len(matching_runs),
                    "runs": [self._format_run_summary(r, history) for r in matching_runs],
                }
            )

        # Task-by-task delta matrix
        all_task_uids = sorted({str(r.get("task_uid")) for r in runs if r.get("task_uid")})
        task_matrix = []
        for t_uid in all_task_uids:
            row_entry: dict[str, Any] = {"task_uid": t_uid, "configs": {}}
            for item in config_data:
                cfg_name = item["config_name"]
                t_runs = [r for r in item["runs"] if r.get("task_uid") == t_uid]
                t_summary = summarize_runs(t_runs)
                row_entry["configs"][cfg_name] = {
                    "runs": t_summary["runs"],
                    "passed": t_summary["passed"],
                    "success_rate": t_summary["success_rate"],
                    "mean_score": t_summary["mean_score"],
                    "mean_duration": t_summary["mean_duration_seconds"],
                    "total_tokens": t_summary["total_tokens"],
                }
            task_matrix.append(row_entry)

        return {
            "configurations": config_data,
            "task_matrix": task_matrix,
            "all_available_configs": [r["config"] for r in ranking],
            "ranking": ranking,
        }

    def compare_runs_side_by_side(self, run_uid_a: str, run_uid_b: str) -> dict[str, Any] | None:
        detail_a = self.get_run_detail(run_uid_a)
        detail_b = self.get_run_detail(run_uid_b)
        if not detail_a or not detail_b:
            return None

        # Compute metric differences
        score_a = detail_a.get("score")
        score_b = detail_b.get("score")
        score_diff = (
            round(score_b - score_a, 4) if (score_a is not None and score_b is not None) else None
        )

        dur_a = detail_a.get("duration_seconds")
        dur_b = detail_b.get("duration_seconds")
        time_ratio = round(dur_b / dur_a, 2) if (dur_a and dur_b and dur_a > 0) else None

        tok_a = (detail_a.get("run", {}).get("observations") or {}).get("total_tokens")
        tok_b = (detail_b.get("run", {}).get("observations") or {}).get("total_tokens")
        token_ratio = round(tok_b / tok_a, 2) if (tok_a and tok_b and tok_a > 0) else None

        return {
            "run_a": detail_a,
            "run_b": detail_b,
            "deltas": {
                "score_diff": score_diff,
                "time_ratio": time_ratio,
                "token_ratio": token_ratio,
            },
        }

    # ------------------------------------------------------------- Internal
    def get_analytics_dataset(self) -> dict[str, Any]:
        """Flat, chart-friendly rows for every run plus the available dimensions."""
        history = self.get_history()
        rows: list[dict[str, Any]] = []
        param_keys: set[str] = set()
        for r in history.runs:
            row = self._format_run_summary(r, history)
            params: dict[str, Any] = {}
            for v in history.variants.get(str(r.get("experiment_uid")), []):
                if v.get("uid") == r.get("variant_uid"):
                    params = {str(k): str(val) for k, val in (v.get("values") or {}).items()}
                    break
            param_keys.update(params)
            task = history.task(str(r.get("task_uid"))) or {}
            row["params"] = params
            row["category"] = task.get("category")
            row["difficulty"] = task.get("difficulty")
            row["verdict"] = row["verdict"] or "unverified"
            rows.append(row)
        return {"rows": rows, "param_keys": sorted(param_keys)}

    def _format_run_summary(self, r: dict[str, Any], history: HistoryData) -> dict[str, Any]:
        duration = duration_seconds(r)
        score = score_of(r)
        verdict = verdict_of(r)
        obs = r.get("observations") or {}
        eval_dict = r.get("evaluation") or {}

        # Get variant configuration string
        var_uid = r.get("variant_uid")
        exp_uid = r.get("experiment_uid")
        config_str = var_uid or ""
        v_list = history.variants.get(str(exp_uid), [])
        for v in v_list:
            if v.get("uid") == var_uid:
                items = sorted(f"{k}={val}" for k, val in (v.get("values") or {}).items())
                config_str = ", ".join(items) if items else str(var_uid)
                break

        return {
            "uid": r.get("uid"),
            "experiment_uid": r.get("experiment_uid"),
            "variant_uid": r.get("variant_uid"),
            "config_str": config_str,
            "task_uid": r.get("task_uid"),
            "agent": r.get("agent"),
            "model": r.get("observed_model") or r.get("requested_model"),
            "status": r.get("status"),
            "verdict": verdict,
            "score": score,
            "passed_tests": eval_dict.get("passed"),
            "failed_tests": eval_dict.get("failed"),
            "total_tests": eval_dict.get("total"),
            "duration_seconds": duration,
            "input_tokens": obs.get("input_tokens"),
            "cached_input_tokens": obs.get("cached_input_tokens"),
            "output_tokens": obs.get("output_tokens"),
            "total_tokens": obs.get("total_tokens"),
            "tool_call_count": obs.get("tool_call_count"),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
        }
