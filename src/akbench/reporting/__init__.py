"""Static reporting: what the history says, in HTML that needs no server.

Reports are built from the recorded history alone, so a report never shows a
number the database does not hold. A failed run, an unverified configuration
or a metric that was never measured is shown as such; none of it is smoothed
away, because a report that flatters its data is not a report.
"""

from akbench.reporting.data import (
    ExperimentReport,
    HistoryData,
    RunReport,
    SubjectReport,
    TaskReport,
    build_agent_report,
    build_category_report,
    build_difficulty_report,
    build_experiment_report,
    build_model_report,
    build_plugin_report,
    build_run_report,
    build_runtime_report,
    build_task_report,
    build_verdict_report,
    collect_history,
    dashboard,
    duration_seconds,
    order_by_start,
    score_of,
    summarize_runs,
    unverified_configurations,
    variant_lookup,
)
from akbench.reporting.render import (
    asset_names,
    render_experiment,
    render_index,
    render_run,
    render_subject,
    render_task,
    slugify,
    write_report_tree,
)

__all__ = [
    "ExperimentReport",
    "HistoryData",
    "RunReport",
    "SubjectReport",
    "TaskReport",
    "asset_names",
    "build_agent_report",
    "build_category_report",
    "build_difficulty_report",
    "build_experiment_report",
    "build_model_report",
    "build_plugin_report",
    "build_run_report",
    "build_runtime_report",
    "build_task_report",
    "build_verdict_report",
    "collect_history",
    "dashboard",
    "duration_seconds",
    "order_by_start",
    "render_experiment",
    "render_index",
    "render_run",
    "render_subject",
    "render_task",
    "score_of",
    "slugify",
    "summarize_runs",
    "unverified_configurations",
    "variant_lookup",
    "write_report_tree",
]
