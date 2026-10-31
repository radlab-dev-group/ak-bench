"""Rendering of the static HTML reports.

The output is a tree of plain files: no server, no JavaScript, no external
asset. A report opened a month later has to read the same as it does today,
and it has to be emailable.

Three things are deliberate:

- everything is escaped, because run records contain agent output;
- an absent value prints as ``not measured`` rather than blank, so a blank
  cell is never mistaken for a zero;
- failed runs and unverified configurations are rendered, never dropped. A
  report that let a reader miss them would be worse than no report.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from akbench.reporting.data import (
    ExperimentReport,
    HistoryData,
    TaskReport,
    build_experiment_report,
    build_task_report,
    dashboard,
    duration_seconds,
    unverified_configurations,
    verdict_of,
)

STYLE_NAME = "assets/style.css"
ASSET_NAMES: tuple[str, ...] = (STYLE_NAME,)
NOT_MEASURED = "not measured"
CSS_TOKEN = "{{css}}"
ROOT_TOKEN = "{{root}}"

STYLE = """
:root {
  --bg: #ffffff; --fg: #16181d; --muted: #5b6472; --line: #d8dde5;
  --pass: #1a7f37; --fail: #b3261e; --warn: #8a6100; --head: #f3f5f8;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1.5rem 4rem; background: var(--bg); color: var(--fg);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 68rem; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.15rem; margin: 2rem 0 .5rem; }
a { color: #1f4fbf; text-decoration: none; }
a:hover { text-decoration: underline; }
.nav { font-size: .9rem; color: var(--muted); margin-bottom: 1.25rem; }
.subtitle { color: var(--muted); margin: 0 0 1.25rem; }
table { border-collapse: collapse; width: 100%; margin: .35rem 0 1rem; }
th, td {
  border-bottom: 1px solid var(--line); padding: .4rem .55rem;
  text-align: left; vertical-align: top; font-variant-numeric: tabular-nums;
}
th { background: var(--head); font-weight: 600; }
td.num, th.num { text-align: right; }
.cards { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1rem 0 1.5rem; }
.card { border: 1px solid var(--line); border-radius: 6px; padding: .6rem .8rem; min-width: 9rem; }
.card .label { color: var(--muted); font-size: .75rem; text-transform: uppercase; }
.card .value { font-size: 1.25rem; font-weight: 600; }
.pass { color: var(--pass); }
.fail { color: var(--fail); }
.warn { color: var(--warn); }
.muted { color: var(--muted); }
.badge { border: 1px solid var(--line); border-radius: 10px; padding: 0 .45rem; font-size: .78rem; }
.notice {
  border-left: 3px solid var(--warn); background: #fffaf0;
  padding: .6rem .8rem; margin: .75rem 0;
}
code { font: .8rem/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
footer { margin-top: 2.5rem; color: var(--muted); font-size: .85rem; }
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def number(value: float | int | None, *, digits: int = 0) -> str:
    """Format a number, or say plainly that it was never measured."""
    if value is None:
        return NOT_MEASURED
    if isinstance(value, bool):
        return esc(value)
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{digits}f}"


def percent(value: float | None) -> str:
    if value is None:
        return NOT_MEASURED
    return f"{value * 100:.1f}%"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return NOT_MEASURED
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)} m {remainder:.0f} s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)} h {int(minutes)} m"


def table(headers: list[str], rows: list[list[str]]) -> str:
    """A table; a header ending in ``#`` is right-aligned as a number."""
    if not headers or not rows:
        return '<p class="muted">nothing recorded</p>'

    def is_num(header: str) -> bool:
        return header.endswith("#")

    head = "".join(
        f'<th class="num">{esc(header[:-2].strip())}</th>'
        if is_num(header)
        else f"<th>{esc(header)}</th>"
        for header in headers
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="num">{cell}</td>' if is_num(header) else f"<td>{cell}</td>"
            for header, cell in zip(headers, row, strict=True)
        )
        + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def cards(items: list[tuple[str, str]]) -> str:
    rendered = "".join(
        f'<div class="card"><div class="label">{esc(label)}</div>'
        f'<div class="value">{value}</div></div>'
        for label, value in items
    )
    return f'<div class="cards">{rendered}</div>'


def page(
    title: str,
    body: str,
    *,
    generated_at: str | None = None,
    standalone: bool = False,
) -> str:
    """One page.

    ``standalone`` inlines the stylesheet and drops the navigation, for a file
    that must read on its own: the HTML form of an export.
    """
    nav = ""
    if not standalone:
        nav = (
            '<p class="nav">'
            f'<a href="{ROOT_TOKEN}index.html">dashboard</a> · '
            f'<a href="{ROOT_TOKEN}agents/index.html">agents</a> · '
            f'<a href="{ROOT_TOKEN}runtimes/index.html">runtimes</a> · '
            f'<a href="{ROOT_TOKEN}plugins/index.html">plugins</a> · '
            f'<a href="{ROOT_TOKEN}models/index.html">models</a> · '
            f'<a href="{ROOT_TOKEN}tasks/index.html">tasks</a></p>'
        )
    head = (
        f"<style>{STYLE}</style>" if standalone else f'<link rel="stylesheet" href="{CSS_TOKEN}">'
    )
    stamp = f"<footer>generated {esc(generated_at)} from the recorded history</footer>"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{esc(title)}</title>"
        f"{head}</head>"
        f"<body><main>{nav}{body}{stamp}</main></body></html>\n"
    )


def _badges(statuses: dict[str, int] | list[str]) -> str:
    items = sorted(statuses.items()) if isinstance(statuses, dict) else [(s, 0) for s in statuses]
    if not items:
        return NOT_MEASURED
    parts = []
    for status, count in items:
        css = "pass" if status == "verified" else "warn"
        label = f"{status} x {count}" if count else str(status)
        parts.append(f'<span class="badge {css}">{esc(label)}</span>')
    return " ".join(parts)


def _notice(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return '<p class="pass">every recorded configuration states it was verified.</p>'
    rows = [
        [
            esc(item.get("kind")),
            esc(item.get("subject")),
            f'<span class="badge warn">{esc(item.get("status"))}</span>',
            esc(item.get("run_uid") or ""),
            esc(item.get("note") or ""),
        ]
        for item in findings
    ]
    return (
        '<div class="notice"><strong>Configurations that are not verified.</strong> '
        "They stay in the report, because a result produced under them is only as "
        "trustworthy as they are.</div>" + table(["kind", "subject", "status", "run", "note"], rows)
    )


def _comparison_table(rows: list[dict[str, Any]], label: str) -> str:
    return table(
        [
            label,
            "runs #",
            "evaluated #",
            "passed #",
            "success rate",
            "mean time",
            "tokens #",
            "statuses",
        ],
        [
            [
                esc(row.get(label)),
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                number(row.get("passed") or 0),
                percent(row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                number(row.get("total_tokens")),
                esc(", ".join(row.get("statuses") or [])),
            ]
            for row in rows
        ],
    )


def _experiment_link(uid: Any) -> str:
    """A link to an experiment report, relative to the page that lists it."""
    return f'<a href="experiments/{esc(uid)}/index.html">{esc(uid)}</a>'


def render_index(data: HistoryData, *, generated_at: str | None = None) -> str:
    stats = dashboard(data)
    body = [
        "<h1>AK-Bench dashboard</h1>",
        '<p class="subtitle">the recorded history: experiments, runs, agents, '
        "runtimes, plugins and models</p>",
        cards(
            [
                ("experiments", number(stats["experiments"])),
                ("runs", number(stats["runs"])),
                ("evaluated", number(stats["evaluated"])),
                ("success rate", percent(stats["success_rate"])),
                ("tasks", number(stats["tasks"])),
                ("total time", duration(stats["total_duration_seconds"])),
                ("mean time", duration(stats["mean_duration_seconds"])),
                ("tokens", number(stats["total_tokens"])),
                ("cost", "not recorded"),
            ]
        ),
        f'<p class="muted">{esc(stats["cost"]["reason"])}</p>',
        "<h2>Verdicts</h2>",
        table(
            ["verdict", "runs #", "share of evaluated"],
            [
                [
                    esc(verdict),
                    number(count),
                    percent(count / stats["evaluated"] if stats["evaluated"] else None),
                ]
                for verdict, count in sorted(stats["verdicts"].items())
            ],
        ),
        "<h2>Experiments</h2>",
        table(
            ["experiment", "type", "runs #", "verdicts", "updated"],
            [
                [
                    _experiment_link(row.get("uid")),
                    esc(row.get("type")),
                    number(row.get("runs") or 0),
                    _verdict_summary(row.get("verdicts") or {}),
                    esc(row.get("updated_at")),
                ]
                for row in data.experiments
            ],
        )
        if data.experiments
        else '<p class="muted">nothing recorded</p>',
        "<h2>Results by category</h2>",
        _comparison_table(stats["by_category"], "category"),
        "<h2>Results by difficulty</h2>",
        _comparison_table(stats["by_difficulty"], "difficulty"),
        "<h2>Agent comparison</h2>",
        _comparison_table(stats["agents"], "agent"),
        "<h2>Runtime and router comparison</h2>",
        _comparison_table(stats["runtimes"], "runtime"),
        "<h2>Plugin comparison</h2>",
        table(
            ["plugin", "runs #", "enabled runs #", "versions", "verification"],
            [
                [
                    esc(row.get("plugin")),
                    number(row.get("runs") or 0),
                    number(row.get("enabled_runs") or 0),
                    esc(", ".join(row.get("versions") or []) or NOT_MEASURED),
                    _badges(row.get("verification_statuses") or {}),
                ]
                for row in stats["plugins"]
            ],
        ),
        "<h2>Model comparison</h2>",
        table(
            ["requested", "observed", "runs #", "source", "verification"],
            [
                [
                    esc(row.get("requested")),
                    esc(row.get("observed")),
                    number(row.get("runs") or 0),
                    esc(", ".join(row.get("sources") or []) or NOT_MEASURED),
                    _badges(row.get("verification_statuses") or {}),
                ]
                for row in stats["models"]
            ],
        ),
        "<h2>Recent experiments</h2>",
        table(
            ["experiment", "title", "updated"],
            [
                [
                    _experiment_link(row.get("uid")),
                    esc(row.get("title")),
                    esc(row.get("updated_at")),
                ]
                for row in stats["recent_experiments"]
            ],
        ),
        "<h2>Not verified</h2>",
        _notice(stats["unverified_configurations"]),
    ]
    return page("AK-Bench dashboard", "".join(body), generated_at=generated_at)


def _runs_table(runs: list[dict[str, Any]]) -> str:
    rows = []
    for run in runs:
        evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), dict) else {}
        observations = (
            run.get("observations") if isinstance(run.get("observations"), dict) else {}
        )
        rows.append(
            [
                esc(run.get("uid")),
                esc(run.get("task_uid")),
                esc(run.get("agent")),
                esc(run.get("variant_uid")),
                esc(run.get("status")),
                esc(verdict_of(run)),
                number(evaluation.get("score"), digits=3),
                duration(duration_seconds(run)),
                number(observations.get("total_tokens")),
                esc(run.get("failure_class")),
                esc(run.get("error_message") or ""),
            ]
        )
    return table(
        [
            "run",
            "task",
            "agent",
            "variant",
            "status",
            "verdict",
            "score #",
            "time",
            "tokens #",
            "failure class",
            "error",
        ],
        rows,
    )


def _not_passed(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if verdict_of(run) != PASSED
        or run.get("status") != "completed"
        or run.get("failure_class")
    ]


PASSED = "passed"


def _artifact_rows(runs: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [
            esc(run.get("uid")),
            esc(artifact.get("kind")),
            f'<code>{esc(artifact.get("path"))}</code>',
            esc(artifact.get("checksum")),
        ]
        for run in runs
        for artifact in run.get("artifacts") or []
    ]


def _verdict_summary(verdicts: dict[str, Any]) -> str:
    return esc(", ".join(f"{key}:{value}" for key, value in sorted(verdicts.items())))


def _experiment_subtitle(experiment: dict[str, Any]) -> str:
    title = experiment.get("title") or ""
    return f'<p class="subtitle">{esc(experiment.get("uid"))} - {esc(title)}</p>'


def _variant_run_count(runs: list[dict[str, Any]], variant_uid: Any) -> int:
    return sum(1 for run in runs if run.get("variant_uid") == variant_uid)


def render_experiment(
    report: ExperimentReport, *, generated_at: str | None = None, standalone: bool = False
) -> str:
    experiment = report.experiment
    summary = report.summary
    body = [
        "<h1>Experiment</h1>",
        _experiment_subtitle(experiment),
        cards(
            [
                ("runs", number(summary.get("runs"))),
                ("evaluated", number(summary.get("evaluated"))),
                ("success rate", percent(summary.get("success_rate"))),
                ("mean time", duration(summary.get("mean_duration_seconds"))),
                ("tokens", number(summary.get("total_tokens"))),
            ]
        ),
        "<h2>Descriptor and validity</h2>",
        table(
            ["field", "value"],
            [
                ["uid", esc(experiment.get("uid"))],
                ["type", esc(experiment.get("type"))],
                ["descriptor", esc(experiment.get("descriptor"))],
                ["config hash", f'<code>{esc(experiment.get("config_hash"))}</code>'],
                ["validity", esc(experiment.get("validity"))],
                ["created", esc(experiment.get("created_at"))],
                ["updated", esc(experiment.get("updated_at"))],
            ],
        ),
        "<h2>Variants</h2>",
        table(
            ["variant", "values", "config hash", "baseline", "runs #"],
            [
                [
                    esc(variant.get("uid")),
                    _values(variant.get("values")),
                    f'<code>{esc(variant.get("config_hash"))}</code>',
                    "yes" if variant.get("is_baseline") else "no",
                    number(_variant_run_count(report.runs, variant.get("uid"))),
                ]
                for variant in report.variants
            ],
        ),
        "<h2>Pinned descriptors</h2>",
        table(
            ["kind", "id", "version", "digest"],
            [
                [
                    esc(row.get("kind")),
                    esc(row.get("id")),
                    esc(row.get("version")),
                    f'<code>{esc(row.get("digest"))}</code>',
                ]
                for row in report.snapshots
            ],
        ),
        "<h2>Metrics</h2>",
        table(
            [
                "metric",
                "group",
                "unit",
                "runs #",
                "measured #",
                "availability",
                "mean #",
                "deviation #",
                "min #",
                "max #",
            ],
            [
                [
                    esc(row.get("metric")),
                    esc(row.get("group")),
                    esc(row.get("unit")),
                    number(row.get("runs") or 0),
                    number(row.get("measured") or 0),
                    percent(row.get("availability")),
                    number(row.get("mean"), digits=4),
                    number(row.get("deviation"), digits=4),
                    number(row.get("min"), digits=4),
                    number(row.get("max"), digits=4),
                ]
                for row in report.metrics
            ],
        ),
        "<h2>Not passed</h2>",
        _runs_table(_not_passed(report.runs)),
        "<h2>All runs</h2>",
        _runs_table(report.runs),
        "<h2>Artifacts</h2>",
        table(["run", "kind", "path", "checksum"], _artifact_rows(report.runs)),
        "<h2>Not verified</h2>",
        _notice(report.unverified),
    ]
    return page(
        f"Experiment {experiment.get('uid')}",
        "".join(body),
        generated_at=generated_at,
        standalone=standalone,
    )


def render_task(report: TaskReport, *, generated_at: str | None = None) -> str:
    task = report.task
    summary = report.summary
    body = [
        "<h1>Task</h1>",
        f'<p class="subtitle">{esc(task.get("uid"))}</p>',
        cards(
            [
                ("runs", number(summary.get("runs"))),
                ("success rate", percent(summary.get("success_rate"))),
                ("mean time", duration(summary.get("mean_duration_seconds"))),
                ("tokens", number(summary.get("total_tokens"))),
            ]
        ),
        "<h2>Definition</h2>",
        table(
            ["field", "value"],
            [
                ["category", esc(task.get("category"))],
                ["difficulty", esc(task.get("difficulty"))],
                ["evaluator", esc(task.get("evaluator"))],
                ["base commit", esc(task.get("base_commit"))],
                ["repository", esc(task.get("repository_uid"))],
                ["snapshot digest", f'<code>{esc(task.get("snapshot_digest"))}</code>'],
            ],
        ),
        "<h2>Runs of this task</h2>",
        _runs_table(report.runs),
        "<h2>Not verified</h2>",
        _notice(report.unverified),
    ]
    return page(f"Task {task.get('uid')}", "".join(body), generated_at=generated_at)


def _values(values: Any) -> str:
    if not values:
        return '<span class="muted">(reference)</span>'
    if isinstance(values, dict):
        return esc(", ".join(f"{key}={value}" for key, value in sorted(values.items())))
    return esc(values)


def render_listing(
    title: str, subtitle: str, rows: list[list[str]], headers: list[str]
) -> str:
    body = f"<h1>{esc(title)}</h1><p class='subtitle'>{esc(subtitle)}</p>" + table(headers, rows)
    return page(title, body)


def asset_names() -> tuple[str, ...]:
    return ASSET_NAMES


def write_report_tree(
    root: Path | str, data: HistoryData, *, generated_at: str | None = None
) -> list[Path]:
    """Write the report tree under ``root``; returns every file written."""
    root = Path(root)
    written: list[Path] = []

    def write(relative: str, document: str, *, depth: int) -> None:
        """Write one page, resolving the css and navigation prefixes for its depth."""
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        prefix = "../" * depth
        rendered = document.replace(CSS_TOKEN, f"{prefix}{STYLE_NAME}").replace(
            ROOT_TOKEN, prefix
        )
        target.write_text(rendered, encoding="utf-8")
        written.append(target)

    stylesheet = root / STYLE_NAME
    stylesheet.parent.mkdir(parents=True, exist_ok=True)
    stylesheet.write_text(STYLE, encoding="utf-8")
    written.append(stylesheet)

    write("index.html", render_index(data, generated_at=generated_at), depth=0)
    for experiment in data.experiments:
        uid = str(experiment["uid"])
        write(
            f"experiments/{uid}/index.html",
            render_experiment(build_experiment_report(data, uid), generated_at=generated_at),
            depth=2,
        )
    for task in data.tasks:
        uid = str(task["uid"])
        write(
            f"tasks/{uid}/index.html",
            render_task(build_task_report(data, uid), generated_at=generated_at),
            depth=2,
        )

    stats = dashboard(data)
    write("tasks/index.html", _task_listing(data), depth=1)
    write(
        "agents/index.html",
        _group_listing("Agents", "one row per agent identity", stats["agents"], "agent"),
        depth=1,
    )
    write(
        "runtimes/index.html",
        _group_listing("Runtimes", "one row per runtime", stats["runtimes"], "runtime"),
        depth=1,
    )
    write("plugins/index.html", _plugin_listing(stats["plugins"]), depth=1)
    write("models/index.html", _model_listing(stats["models"]), depth=1)
    return written


def _task_listing(data: HistoryData) -> str:
    rows = [
        [
            f'<a href="{esc(row["uid"])}/index.html">{esc(row["uid"])}</a>',
            esc(row.get("category")),
            esc(row.get("difficulty")),
            esc(row.get("evaluator")),
            number(row.get("runs") or 0),
        ]
        for row in data.tasks
    ]
    return render_listing(
        "Tasks",
        "every recorded task",
        rows,
        ["task", "category", "difficulty", "evaluator", "runs #"],
    )


def _group_listing(title: str, subtitle: str, rows: list[dict[str, Any]], label: str) -> str:
    return render_listing(
        title,
        subtitle,
        [
            [
                esc(row.get(label)),
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                number(row.get("passed") or 0),
                percent(row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                number(row.get("total_tokens")),
                esc(", ".join(row.get("statuses") or [])),
            ]
            for row in rows
        ],
        [
            label,
            "runs #",
            "evaluated #",
            "passed #",
            "success rate",
            "mean time",
            "tokens #",
            "statuses",
        ],
    )


def _plugin_listing(rows: list[dict[str, Any]]) -> str:
    return render_listing(
        "Plugins",
        "what the history says about each plugin",
        [
            [
                esc(row.get("plugin")),
                number(row.get("runs") or 0),
                number(row.get("enabled_runs") or 0),
                esc(", ".join(row.get("versions") or []) or NOT_MEASURED),
                _badges(row.get("verification_statuses") or {}),
                "yes" if row.get("verified") else "no",
            ]
            for row in rows
        ],
        ["plugin", "runs #", "enabled runs #", "versions", "verification", "all verified"],
    )


def _model_listing(rows: list[dict[str, Any]]) -> str:
    return render_listing(
        "Models",
        "requested versus observed model, with the trust the observed value deserves",
        [
            [
                esc(row.get("requested")),
                esc(row.get("observed")),
                number(row.get("runs") or 0),
                esc(", ".join(row.get("sources") or []) or NOT_MEASURED),
                _badges(row.get("verification_statuses") or {}),
            ]
            for row in rows
        ],
        ["requested", "observed", "runs #", "source", "verification"],
    )


def experiment_unverified(data: HistoryData, uid: str) -> list[dict[str, Any]]:
    """Exposed for tests: the unverified findings of one experiment."""
    return unverified_configurations(
        HistoryData(
            experiments=[row for row in data.experiments if row.get("uid") == uid],
            plugins=[
                row
                for row in data.plugins
                if row.get("run_uid")
                in {run.get("uid") for run in data.runs_for_experiment(uid)}
            ],
            models=[
                row
                for row in data.models
                if row.get("run_uid")
                in {run.get("uid") for run in data.runs_for_experiment(uid)}
            ],
        )
    )
