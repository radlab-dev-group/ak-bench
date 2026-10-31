"""Static reporting: what the history says, in HTML that needs no server.

Reports are built from the recorded history alone, so a report never shows a
number the database does not hold. A failed run, an unverified configuration
or a metric that was never measured is shown as such; none of it is smoothed
away, because a report that flatters its data is not a report.
"""

from akbench.reporting.data import (
    ExperimentReport,
    HistoryData,
    TaskReport,
    build_experiment_report,
    build_task_report,
    collect_history,
    dashboard,
    duration_seconds,
    summarize_runs,
    unverified_configurations,
)
from akbench.reporting.render import (
    asset_names,
    render_experiment,
    render_index,
    render_task,
    write_report_tree,
)

__all__ = [
    "ExperimentReport",
    "HistoryData",
    "TaskReport",
    "asset_names",
    "build_experiment_report",
    "build_task_report",
    "collect_history",
    "dashboard",
    "duration_seconds",
    "render_experiment",
    "render_index",
    "render_task",
    "summarize_runs",
    "unverified_configurations",
    "write_report_tree",
]
